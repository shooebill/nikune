"""nikune/meat_focus.py のテスト（実APIは呼ばない。Jev と写真の取得はモック）"""

from typing import Any, List
from unittest import TestCase, mock

from nikune.jev_checker import JevChecker, JevImage, JevResult
from nikune.meat_focus import (
    MEAT_MAIN_KEY,
    MEAT_MAIN_THRESHOLD,
    PHOTO_REF,
    PHOTO_UNAVAILABLE_MARKER,
    UNAVAILABLE_MARKER,
    MeatFocusVerdict,
    fetch_photo,
    judge_meat_focus,
)

PHOTO = JevImage(data=b"\xff\xd8jpeg", format="jpg")


def _ok(probability: float) -> JevResult:
    return JevResult(status="ok", nouls={MEAT_MAIN_KEY: probability}, model="jev-1.13.0")


ERROR = JevResult(status="error", error="HTTP 400")


def _checker(results: List[JevResult]) -> mock.MagicMock:
    checker = mock.MagicMock(spec=JevChecker)
    checker.enabled = True
    checker.ask.side_effect = results
    return checker


class JudgeMeatFocusTests(TestCase):
    def test_photo_is_sent_with_the_text(self) -> None:
        checker = _checker([_ok(0.15)])

        with mock.patch("nikune.meat_focus.fetch_photo", return_value=PHOTO):
            verdict = judge_meat_focus(checker, "t1", "そうめん", "https://example.com/t1.jpg")

        assert verdict is not None
        self.assertAlmostEqual(verdict.probability, 0.15)
        self.assertTrue(verdict.with_photo)
        self.assertFalse(verdict.is_meat_main)
        state, questions = checker.ask.call_args.args
        self.assertEqual(state["candidate_post"], {"text": "そうめん", "photo": PHOTO_REF})
        self.assertIn("candidate_post.photo", questions[MEAT_MAIN_KEY].instructions)
        self.assertEqual(checker.ask.call_args.kwargs["images"], {PHOTO_REF: PHOTO})

    def test_failed_photo_request_is_retried_without_the_photo(self) -> None:
        checker = _checker([ERROR, _ok(0.9)])

        with (
            mock.patch("nikune.meat_focus.fetch_photo", return_value=PHOTO),
            self.assertLogs("nikune.meat_focus", level="WARNING") as logs,
        ):
            verdict = judge_meat_focus(checker, "t1", "焼肉", "https://example.com/t1.jpg")

        assert verdict is not None
        self.assertFalse(verdict.with_photo)
        self.assertTrue(verdict.is_meat_main)
        self.assertEqual(checker.ask.call_count, 2)
        state, _ = checker.ask.call_args.args
        self.assertEqual(state["candidate_post"], {"text": "焼肉"})
        self.assertNotIn("images", checker.ask.call_args.kwargs)
        self.assertTrue(any(PHOTO_UNAVAILABLE_MARKER in line for line in logs.output))

    def test_photo_that_cannot_be_fetched_is_judged_from_the_text_without_a_warning(self) -> None:
        checker = _checker([_ok(0.9)])

        with (
            mock.patch("nikune.meat_focus.fetch_photo", return_value=None),
            self.assertNoLogs("nikune.meat_focus", level="WARNING"),
        ):
            verdict = judge_meat_focus(checker, "t1", "焼肉", "https://example.com/t1.jpg")

        assert verdict is not None
        self.assertFalse(verdict.with_photo)
        self.assertEqual(checker.ask.call_count, 1)

    def test_returns_none_when_jev_fails(self) -> None:
        checker = _checker([ERROR])

        with self.assertLogs("nikune.meat_focus", level="WARNING") as logs:
            verdict = judge_meat_focus(checker, "t1", "焼肉")

        self.assertIsNone(verdict)
        self.assertTrue(any(UNAVAILABLE_MARKER in line for line in logs.output))

    def test_disabled_checker_is_not_asked(self) -> None:
        checker = mock.MagicMock(spec=JevChecker)
        checker.enabled = False

        with mock.patch("nikune.meat_focus.fetch_photo") as fetch:
            self.assertIsNone(judge_meat_focus(checker, "t1", "焼肉", "https://example.com/t1.jpg"))

        checker.ask.assert_not_called()
        fetch.assert_not_called()

    def test_threshold(self) -> None:
        self.assertTrue(MeatFocusVerdict(MEAT_MAIN_THRESHOLD, with_photo=True).is_meat_main)
        self.assertFalse(MeatFocusVerdict(MEAT_MAIN_THRESHOLD - 0.01, with_photo=True).is_meat_main)


def _response(content: bytes = b"\xff\xd8jpeg", content_type: str = "image/jpeg") -> mock.MagicMock:
    response = mock.MagicMock()
    response.content = content
    response.headers = {"Content-Type": content_type}
    return response


class FetchPhotoTests(TestCase):
    def _fetch(self, url: str, response: Any) -> tuple[Any, mock.MagicMock]:
        with mock.patch("nikune.meat_focus.requests.get", return_value=response) as get:
            return fetch_photo(url), get

    def test_x_images_are_fetched_in_the_small_size(self) -> None:
        photo, get = self._fetch("https://pbs.twimg.com/media/abc.jpg", _response())

        self.assertEqual(photo, PHOTO)
        self.assertEqual(get.call_args.args[0], "https://pbs.twimg.com/media/abc.jpg?name=small")

    def test_other_urls_are_fetched_as_they_are(self) -> None:
        _, get = self._fetch("https://example.com/a.png", _response(content_type="image/png"))

        self.assertEqual(get.call_args.args[0], "https://example.com/a.png")

    def test_png_format_comes_from_the_content_type(self) -> None:
        photo, _ = self._fetch("https://example.com/a", _response(content_type="image/png"))

        assert photo is not None
        self.assertEqual(photo.format, "png")

    def test_unsupported_or_too_large_images_are_not_used(self) -> None:
        with mock.patch("nikune.meat_focus.MAX_PHOTO_BYTES", 4):
            photo, _ = self._fetch("https://example.com/a.jpg", _response(content=b"12345"))
        self.assertIsNone(photo)

        photo, _ = self._fetch("https://example.com/a.webp", _response(content_type="image/webp"))
        self.assertIsNone(photo)

    def test_fetch_errors_return_none(self) -> None:
        with mock.patch("nikune.meat_focus.requests.get", side_effect=RuntimeError("boom")):
            self.assertIsNone(fetch_photo("https://example.com/a.jpg"))
