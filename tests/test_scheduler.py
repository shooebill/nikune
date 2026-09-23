"""
バグ回帰テスト: 投稿失敗時にテンプレートのクールダウンだけが消費されないことを確認する

過去の不具合:
    content_generator.generate_tweet_content()がコンテンツ生成の時点で
    テンプレートの使用履歴（Redisクールダウン）を記録してしまっていたため、
    その後のtwitter_client.post_tweet()がAPIエラー等で失敗しても
    クールダウンだけが消費されたままになり、ロールバックがなかった。

    修正後は、generate_tweet_content()自体は副作用を持たず、呼び出し元
    （SchedulerManagerの_scheduled_post/post_now）がpost_tweet()の成功を
    確認した後にのみcontent_generator.record_tweet_usage()を呼ぶ。
"""

from typing import List, Mapping, Optional
from unittest import TestCase, mock

from typesafe_sdk import JSONContent

from nikune.content_generator import GeneratedTweetContent
from nikune.jev_checker import JevChecker, JevQuestion, JevResult
from nikune.post_safety import OFFENSIVE_KEY, PROMOTION_KEY
from nikune.scheduler import SchedulerManager


def _make_scheduler() -> "tuple[SchedulerManager, mock.MagicMock, mock.MagicMock]":
    db_manager = mock.MagicMock()
    content_generator = mock.MagicMock()
    twitter_client = mock.MagicMock()

    scheduler = SchedulerManager(
        db_manager=db_manager,
        content_generator=content_generator,
        twitter_client=twitter_client,
        dry_run=True,
    )
    return scheduler, content_generator, twitter_client


class PostNowCooldownRollbackTests(TestCase):
    def test_does_not_record_usage_when_post_fails(self) -> None:
        scheduler, content_generator, twitter_client = _make_scheduler()
        content_generator.generate_tweet_content.return_value = GeneratedTweetContent(text="テスト", template_id=1)
        twitter_client.post_tweet.return_value = None  # 投稿失敗

        result = scheduler.post_now()

        self.assertFalse(result)
        content_generator.record_tweet_usage.assert_not_called()

    def test_records_usage_when_post_succeeds(self) -> None:
        scheduler, content_generator, twitter_client = _make_scheduler()
        content_generator.generate_tweet_content.return_value = GeneratedTweetContent(text="テスト", template_id=1)
        twitter_client.post_tweet.return_value = "1234567890"  # 投稿成功

        result = scheduler.post_now()

        self.assertTrue(result)
        content_generator.record_tweet_usage.assert_called_once_with(1, "テスト")

    def test_does_not_record_usage_when_content_generation_fails(self) -> None:
        scheduler, content_generator, twitter_client = _make_scheduler()
        content_generator.generate_tweet_content.return_value = None

        result = scheduler.post_now()

        self.assertFalse(result)
        twitter_client.post_tweet.assert_not_called()
        content_generator.record_tweet_usage.assert_not_called()


class ScheduledPostCooldownRollbackTests(TestCase):
    def test_does_not_record_usage_when_post_fails(self) -> None:
        scheduler, content_generator, twitter_client = _make_scheduler()
        content_generator.generate_tweet_content.return_value = GeneratedTweetContent(text="テスト", template_id=2)
        twitter_client.post_tweet.return_value = None  # 投稿失敗

        scheduler._scheduled_post(categories=["お肉"], random_delay=False)

        content_generator.record_tweet_usage.assert_not_called()

    def test_records_usage_when_post_succeeds(self) -> None:
        scheduler, content_generator, twitter_client = _make_scheduler()
        content_generator.generate_tweet_content.return_value = GeneratedTweetContent(text="テスト", template_id=2)
        twitter_client.post_tweet.return_value = "999"  # 投稿成功

        scheduler._scheduled_post(categories=["お肉"], random_delay=False)

        content_generator.record_tweet_usage.assert_called_once_with(2, "テスト")


class _RecordingChecker(JevChecker):
    """ask() の呼び出しを記録し、固定の結果（または例外）を返すテスト用チェッカー（実APIは呼ばない）"""

    def __init__(self, result: Optional[JevResult] = None, error: Optional[Exception] = None) -> None:
        super().__init__(api_key="fake-test-key")
        self.result = result
        self.error = error
        self.texts: List[str] = []
        self.events: Optional[List[str]] = None

    def ask(self, state: JSONContent, questions: Mapping[str, JevQuestion]) -> JevResult:
        assert isinstance(state, dict) and isinstance(state["post"], dict)
        self.texts.append(str(state["post"]["text"]))
        if self.events is not None:
            self.events.append("check")
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


NG_RESULT = JevResult(status="ok", nouls={PROMOTION_KEY: 0.99, OFFENSIVE_KEY: 0.99}, model="jev-1.13.0")


def _make_checked_scheduler(
    checker: JevChecker,
) -> "tuple[SchedulerManager, mock.MagicMock, mock.MagicMock]":
    content_generator = mock.MagicMock()
    twitter_client = mock.MagicMock()
    content_generator.generate_tweet_content.return_value = GeneratedTweetContent(text="テスト", template_id=5)
    twitter_client.post_tweet.return_value = "111"
    scheduler = SchedulerManager(
        db_manager=mock.MagicMock(),
        content_generator=content_generator,
        twitter_client=twitter_client,
        dry_run=True,
        jev_checker=checker,
    )
    return scheduler, content_generator, twitter_client


def _run_route(scheduler: SchedulerManager, route: str) -> None:
    if route == "scheduled":
        scheduler._scheduled_post(categories=["お肉"], random_delay=False)
    elif route == "post_now":
        scheduler.post_now()
    else:
        scheduler.post_custom_tweet("テスト")


ROUTES = ("scheduled", "post_now", "custom")


class PrePostCheckTests(TestCase):
    """投稿直前チェック（Jev）は3経路すべてで post_tweet() の直前に呼ばれ、どんな結果でも投稿を止めない"""

    def setUp(self) -> None:
        # 実行ディレクトリに data/persona.tsv があっても読まない（テストを環境に依存させない）
        patcher = mock.patch("nikune.post_safety.PERSONA_FILE", "/nonexistent/persona.tsv")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_check_runs_before_post_on_all_routes_and_ng_still_posts(self) -> None:
        for route in ROUTES:
            with self.subTest(route=route):
                checker = _RecordingChecker(NG_RESULT)
                scheduler, _, twitter_client = _make_checked_scheduler(checker)
                events: List[str] = []
                checker.events = events

                def post(text: str, events: List[str] = events) -> str:
                    events.append("post")
                    return "111"

                twitter_client.post_tweet.side_effect = post

                with self.assertLogs("nikune.post_safety", level="WARNING") as captured:
                    _run_route(scheduler, route)

                self.assertEqual(checker.texts, ["テスト"])
                self.assertEqual(events, ["check", "post"])  # 判定は投稿の直前に1回
                twitter_client.post_tweet.assert_called_once_with("テスト")
                self.assertTrue(any(f"route={route}" in line and "decision=WARN" in line for line in captured.output))

    def test_template_id_is_logged_for_template_routes(self) -> None:
        checker = _RecordingChecker(NG_RESULT)
        scheduler, _, _ = _make_checked_scheduler(checker)
        with self.assertLogs("nikune.post_safety", level="WARNING") as captured:
            scheduler.post_now()
        self.assertIn("template=5", captured.output[-1])

    def test_api_failure_still_posts_on_all_routes(self) -> None:
        for route in ROUTES:
            with self.subTest(route=route):
                checker = _RecordingChecker(JevResult(status="error", error="APITimeoutError: timeout"))
                scheduler, content_generator, twitter_client = _make_checked_scheduler(checker)

                with self.assertLogs("nikune.post_safety", level="WARNING") as captured:
                    _run_route(scheduler, route)

                twitter_client.post_tweet.assert_called_once_with("テスト")
                self.assertTrue(any("decision=UNCHECKED" in line for line in captured.output))
                if route != "custom":
                    content_generator.record_tweet_usage.assert_called_once_with(5, "テスト")

    def test_exception_in_check_does_not_stop_posting(self) -> None:
        for route in ROUTES:
            with self.subTest(route=route):
                scheduler, _, twitter_client = _make_checked_scheduler(_RecordingChecker(error=RuntimeError("boom")))
                with self.assertLogs("nikune.post_safety", level="WARNING"):
                    _run_route(scheduler, route)
                twitter_client.post_tweet.assert_called_once_with("テスト")

    def test_exception_outside_evaluate_does_not_stop_posting(self) -> None:
        scheduler, _, twitter_client = _make_checked_scheduler(_RecordingChecker(NG_RESULT))
        with mock.patch("nikune.scheduler.evaluate_post", side_effect=RuntimeError("boom")):
            self.assertTrue(scheduler.post_now())
        twitter_client.post_tweet.assert_called_once_with("テスト")

    def test_without_api_key_posts_as_before(self) -> None:
        # conftest.py により TYPESAFE_API_KEY は未設定扱い → 設定から作るチェッカーは機能オフ
        with mock.patch("nikune.jev_checker.TypeSafeClient") as client_cls:
            content_generator = mock.MagicMock()
            twitter_client = mock.MagicMock()
            content_generator.generate_tweet_content.return_value = GeneratedTweetContent(text="テスト", template_id=5)
            twitter_client.post_tweet.return_value = "111"
            scheduler = SchedulerManager(
                db_manager=mock.MagicMock(),
                content_generator=content_generator,
                twitter_client=twitter_client,
                dry_run=True,
            )
            self.assertFalse(scheduler.jev_checker.enabled)
            for route in ROUTES:
                _run_route(scheduler, route)
        client_cls.assert_not_called()
        self.assertEqual(twitter_client.post_tweet.call_count, 3)

    def test_blocking_switch_stops_post_when_enabled(self) -> None:
        # 将来「止める」に切り替えた場合の動作（現状の既定値では止めない）
        scheduler, content_generator, twitter_client = _make_checked_scheduler(_RecordingChecker(NG_RESULT))
        with mock.patch("nikune.post_safety.BLOCK_ON_WARN", True), self.assertLogs(level="WARNING"):
            self.assertFalse(scheduler.post_now())
        twitter_client.post_tweet.assert_not_called()
        content_generator.record_tweet_usage.assert_not_called()

    def test_quote_retweeter_shares_the_injected_checker(self) -> None:
        checker = _RecordingChecker(NG_RESULT)
        scheduler, _, _ = _make_checked_scheduler(checker)
        self.assertIs(scheduler.auto_quote_retweeter.jev_checker, checker)
