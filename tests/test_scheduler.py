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

from unittest import TestCase, mock

from nikune.content_generator import GeneratedTweetContent
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
