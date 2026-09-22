"""
バグ回帰テスト: 引用RT（疑似引用リツイート）でURLが途中で切れる不具合の確認

過去の不具合:
    pseudo_quote_tweet()のコメント文字数バジェット（250文字）はTwitterのt.co短縮
    （約23文字）を前提にしていたが、post_tweet()側の文字数チェックは短縮前の
    生のx.com URL（40〜60文字程度）を含めた全体の長さの単純なlen()で再チェックし、
    280文字を超えた場合にtext[:277]+'...'で末尾を単純に切り詰めていたため、
    URL自体が途中で切れて壊れたリンクになることがあった。

修正後は、末尾にURLがある場合はURLを保護し、それより前の本文（コメント）側だけを
切り詰める。
"""

from types import SimpleNamespace
from unittest import TestCase, mock

from nikune.twitter_client import (
    TwitterClient,
    _safe_text_length,
    _truncate_text_preserving_trailing_url,
)


def _make_live_client_with_mock_api() -> "tuple[TwitterClient, mock.MagicMock]":
    # TwitterClient.__init__（実API接続のセットアップ）をスキップし、
    # postTweet呼び出し部分だけを単体テストする
    client = object.__new__(TwitterClient)
    client.dry_run = False
    mock_client = mock.MagicMock()
    mock_client.create_tweet.return_value = SimpleNamespace(data={"id": "999"})
    client.client = mock_client  # type: ignore[assignment]
    client.api = mock.MagicMock()  # type: ignore[assignment]
    return client, mock_client


class TruncateTextPreservingTrailingUrlTests(TestCase):
    def test_long_comment_with_trailing_url_keeps_url_intact(self) -> None:
        url = "https://x.com/some_example_username/status/1234567890123456789"
        prefix = "テスト" * 100  # 十分に長いコメント（280文字超過を確実に発生させる）
        text = f"{prefix} {url}"

        result = _truncate_text_preserving_trailing_url(text, 280)

        self.assertTrue(result.endswith(url), msg=f"URLが壊れている: {result!r}")
        self.assertLessEqual(_safe_text_length(result), 280)

    def test_text_without_url_falls_back_to_plain_truncation(self) -> None:
        text = "あ" * 300

        result = _truncate_text_preserving_trailing_url(text, 280)

        self.assertLessEqual(_safe_text_length(result), 280)
        self.assertTrue(result.endswith("..."))

    def test_text_within_limit_is_unchanged(self) -> None:
        url = "https://x.com/user/status/123"
        text = f"テスト {url}"

        result = _truncate_text_preserving_trailing_url(text, 280)

        self.assertEqual(result, text)


class PostTweetUrlTruncationTests(TestCase):
    def test_post_tweet_preserves_url_when_text_too_long(self) -> None:
        client, mock_client = _make_live_client_with_mock_api()
        url = "https://x.com/some_example_username/status/1234567890123456789"
        comment = "テスト" * 100
        text = f"{comment} {url}"

        client.post_tweet(text)

        posted_text = mock_client.create_tweet.call_args.kwargs["text"]
        self.assertTrue(posted_text.endswith(url), msg=f"URLが壊れている: {posted_text!r}")
        self.assertLessEqual(_safe_text_length(posted_text), 280)

    def test_post_tweet_leaves_short_text_with_url_unchanged(self) -> None:
        client, mock_client = _make_live_client_with_mock_api()
        url = "https://x.com/user/status/123"
        text = f"テスト {url}"

        client.post_tweet(text)

        posted_text = mock_client.create_tweet.call_args.kwargs["text"]
        self.assertEqual(posted_text, text)
