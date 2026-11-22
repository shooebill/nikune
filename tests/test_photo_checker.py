from types import SimpleNamespace
from typing import Any
from unittest import TestCase, mock

from nikune.photo_checker import PhotoChecker, _CommentAnswer, _PhotoAnswer, _WrittenAnswer

DISHES = ["寿司", "焼肉", "ラーメン"]


def _response(answer: Any, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(parsed_output=answer, stop_reason=stop_reason, model="test-model")


def _photo_answer(**overrides: Any) -> _PhotoAnswer:
    fields: dict[str, Any] = {
        "is_food": True,
        "shows_meat": False,
        "dishes": [],
        "meats": [],
        "meal": "unknown",
        "light": "unknown",
    }
    fields.update(overrides)
    return _PhotoAnswer(**fields)


def _checker(client: Any) -> PhotoChecker:
    return PhotoChecker(api_key=None, model="test-model", timeout_seconds=1, client=client)


class PhotoCheckerTests(TestCase):
    def test_without_key_it_is_disabled_and_returns_none(self) -> None:
        checker = PhotoChecker(api_key=None, model="test-model", timeout_seconds=1)

        self.assertFalse(checker.enabled)
        self.assertIsNone(checker.check(["https://example.com/a.jpg"], DISHES))

    def test_answer_is_returned_and_unknown_dishes_are_dropped(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(
            _photo_answer(is_food=True, shows_meat=True, dishes=["焼肉", "一覧にない料理"])
        )

        verdict = _checker(client).check(["https://example.com/a.jpg"], DISHES)

        assert verdict is not None
        self.assertTrue(verdict.is_food)
        self.assertTrue(verdict.shows_meat)
        self.assertEqual(verdict.dishes, ["焼肉"])
        self.assertEqual(verdict.model, "test-model")

    def test_the_photo_is_sent_by_url_with_the_dish_list_and_the_post_text(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_photo_answer(is_food=False, shows_meat=False, dishes=[]))

        _checker(client).check(["https://example.com/a.jpg"], DISHES, "豚肉の串です")

        kwargs = client.messages.parse.call_args.kwargs
        image, text = kwargs["messages"][0]["content"]
        self.assertEqual(image["source"], {"type": "url", "url": "https://example.com/a.jpg"})
        self.assertIn("寿司、焼肉、ラーメン", text["text"])
        self.assertIn("豚肉の串です", text["text"])
        self.assertEqual(kwargs["model"], "test-model")

    def test_all_photos_are_sent_in_order_up_to_the_limit(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_photo_answer())
        urls = [f"https://example.com/{i}.jpg" for i in range(5)]
        checker = PhotoChecker(api_key=None, model="test-model", timeout_seconds=1, client=client, max_photos=4)

        checker.check(urls, DISHES)

        content = client.messages.parse.call_args.kwargs["messages"][0]["content"]
        self.assertEqual([part["source"]["url"] for part in content[:-1]], urls[:4])
        self.assertEqual(content[-1]["type"], "text")

    def test_token_usage_is_logged_with_the_number_of_photos(self) -> None:
        client = mock.MagicMock()
        response = _response(_photo_answer())
        response.usage = SimpleNamespace(input_tokens=4321, output_tokens=56)
        client.messages.parse.return_value = response

        with self.assertLogs("nikune.photo_checker", level="INFO") as logs:
            _checker(client).check(["https://example.com/a.jpg", "https://example.com/b.jpg"], DISHES)

        self.assertTrue(any("images=2 input_tokens=4321 output_tokens=56" in line for line in logs.output))

    def test_non_food_photo_never_reports_meat_or_dishes(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_photo_answer(is_food=False, shows_meat=True, dishes=["焼肉"]))

        verdict = _checker(client).check(["https://example.com/a.jpg"], DISHES)

        assert verdict is not None
        self.assertFalse(verdict.shows_meat)
        self.assertEqual(verdict.dishes, [])

    def test_meat_kinds_meal_and_light_are_returned(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(
            _photo_answer(shows_meat=True, meats=["鶏肉", "鶏肉"], meal="lunch", light="night")
        )

        verdict = _checker(client).check(["https://example.com/a.jpg"], DISHES, "新店のランチ")

        assert verdict is not None
        self.assertEqual(verdict.meats, ["鶏肉"])
        self.assertEqual(verdict.meal, "lunch")
        self.assertEqual(verdict.light, "night")

    def test_unknown_meal_and_light_become_none(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_photo_answer())

        verdict = _checker(client).check(["https://example.com/a.jpg"], DISHES)

        assert verdict is not None
        self.assertEqual(verdict.meats, [])
        self.assertIsNone(verdict.meal)
        self.assertIsNone(verdict.light)

    def test_breakfast_answer_is_returned_as_morning(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_photo_answer(meal="breakfast", light="day"))

        verdict = _checker(client).check(["https://example.com/a.jpg"], DISHES)

        assert verdict is not None
        self.assertEqual(verdict.meal, "morning")
        self.assertEqual(verdict.light, "day")

    def test_api_failure_returns_none_without_raising(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.side_effect = RuntimeError("boom")

        self.assertIsNone(_checker(client).check(["https://example.com/a.jpg"], DISHES))

    def test_refusal_or_missing_answer_returns_none(self) -> None:
        for response in [_response(None, stop_reason="refusal"), _response(None)]:
            with self.subTest(stop_reason=response.stop_reason):
                client = mock.MagicMock()
                client.messages.parse.return_value = response

                self.assertIsNone(_checker(client).check(["https://example.com/a.jpg"], DISHES))


class CommentFitsTests(TestCase):
    def test_without_key_it_returns_none(self) -> None:
        checker = PhotoChecker(api_key=None, model="test-model", timeout_seconds=1)

        self.assertIsNone(checker.comment_fits("肉ね！", "焼肉たべた"))

    def test_verdict_is_returned_with_a_shortened_reason(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_CommentAnswer(fits=False, reason="あ" * 200))

        verdict = _checker(client).comment_fits("肉ね！", "焼肉たべた")

        assert verdict is not None
        self.assertFalse(verdict.fits)
        self.assertEqual(len(verdict.reason), 60)

    def test_comment_and_post_text_are_sent_with_the_photo(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_CommentAnswer(fits=True, reason="ok"))

        _checker(client).comment_fits("肉ね！", "焼肉たべた", ["https://example.com/a.jpg"])

        image, text = client.messages.parse.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(image["source"], {"type": "url", "url": "https://example.com/a.jpg"})
        self.assertIn("肉ね！", text["text"])
        self.assertIn("焼肉たべた", text["text"])

    def test_post_without_a_photo_is_checked_by_text_only(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_CommentAnswer(fits=True, reason="ok"))

        _checker(client).comment_fits("肉ね！", "焼肉たべた")

        content = client.messages.parse.call_args.kwargs["messages"][0]["content"]
        self.assertEqual([part["type"] for part in content], ["text"])

    def test_failure_or_wrong_answer_shape_returns_none(self) -> None:
        wrong_shape = _response(_photo_answer(is_food=True, shows_meat=True, dishes=[]))
        for outcome in [RuntimeError("boom"), wrong_shape, _response(None, stop_reason="refusal")]:
            with self.subTest(outcome=type(outcome).__name__):
                client = mock.MagicMock()
                if isinstance(outcome, Exception):
                    client.messages.parse.side_effect = outcome
                else:
                    client.messages.parse.return_value = outcome

                self.assertIsNone(_checker(client).comment_fits("肉ね！", "焼肉たべた"))


PERSONA = [{"category": "口調", "item": "語尾", "content": "テスト用の語尾", "note": "テスト用の補足"}]


class WriteCommentTests(TestCase):
    def _writer(self, client: Any) -> PhotoChecker:
        return PhotoChecker(
            api_key=None, model="judge-model", timeout_seconds=1, client=client, writer_model="writer-model"
        )

    def test_without_key_it_returns_none(self) -> None:
        checker = PhotoChecker(api_key=None, model="test-model", timeout_seconds=1)

        self.assertIsNone(checker.write_comment("焼肉たべたい", PERSONA, ["例のセリフ"]))

    def test_written_text_is_returned_stripped_with_the_model(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_WrittenAnswer(text="  書いたセリフ \n"))

        written = self._writer(client).write_comment("焼肉たべたい", PERSONA, ["例のセリフ"])

        assert written is not None
        self.assertEqual(written.text, "書いたセリフ")
        self.assertEqual(written.model, "test-model")

    def test_the_writer_model_persona_examples_and_post_are_sent(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_WrittenAnswer(text="書いたセリフ"))

        self._writer(client).write_comment("焼肉たべたい", PERSONA, ["例のセリフ"], ["https://example.com/a.jpg"])

        kwargs = client.messages.parse.call_args.kwargs
        image, text = kwargs["messages"][0]["content"]
        self.assertEqual(image["source"], {"type": "url", "url": "https://example.com/a.jpg"})
        self.assertIn("口調 / 語尾: テスト用の語尾（テスト用の補足）", text["text"])
        self.assertIn("- 例のセリフ", text["text"])
        self.assertIn("焼肉たべたい", text["text"])
        self.assertEqual(kwargs["model"], "writer-model")
        self.assertEqual(kwargs["output_config"], {"effort": "medium"})

    def test_checks_still_use_the_judge_model(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.return_value = _response(_CommentAnswer(fits=True, reason="ok"))

        self._writer(client).comment_fits("肉ね！", "焼肉たべた")

        self.assertEqual(client.messages.parse.call_args.kwargs["model"], "judge-model")
        self.assertEqual(client.messages.parse.call_args.kwargs["output_config"], {"effort": "low"})

    def test_api_failure_returns_none_and_logs_the_marker(self) -> None:
        client = mock.MagicMock()
        client.messages.parse.side_effect = RuntimeError("boom")

        with self.assertLogs("nikune.photo_checker", level="WARNING") as logs:
            self.assertIsNone(self._writer(client).write_comment("焼肉たべたい", PERSONA, []))
        self.assertIn("📷 Comment writing unavailable", logs.output[0])
