"""
nikune bot Twitter API client
Twitter APIとの接続、ツイート投稿などを担当
"""

import logging
import re
import unicodedata
from types import SimpleNamespace
from typing import Any, List, Optional

import tweepy

from config.settings import (
    BOT_NAME,
    TWITTER_ACCESS_TOKEN,
    TWITTER_ACCESS_TOKEN_SECRET,
    TWITTER_API_KEY,
    TWITTER_API_SECRET,
    TWITTER_BEARER_TOKEN,
)

# 定数定義
# 疑似引用リツイート（コメント+URL方式）のコメント最大文字数
# （Twitter280文字制限から、URL短縮後の約23文字＋区切りスペースを考慮）
MAX_QUOTE_COMMENT_LENGTH = 250


def _safe_text_length(text: str) -> int:
    """
    Unicode安全な文字カウント

    Args:
        text: カウント対象のテキスト

    Returns:
        正規化後の文字数

    Note:
        unicodedataを使用して正規化を行い、より正確な文字数をカウント
        ただし、Twitter APIの公式カウントロジック（絵文字や結合文字の特殊な処理）とは異なる可能性があります
        TODO: 将来的にはtwitter-text-parserライブラリの使用を検討
    """
    # NFCで正規化（結合文字を正規化）
    normalized = unicodedata.normalize("NFC", text)
    return len(normalized)


def _truncate_comment(comment: str, max_length: int) -> str:
    """
    Unicode安全な文字数チェックを行い、上限を超える場合は安全に切り詰める

    Args:
        comment: 対象コメント
        max_length: 最大文字数

    Note:
        結合文字・絵文字を考慮したNFC正規化後に切り詰め、再度文字数チェックして調整する。
        TODO: より正確な文字数カウントのため twitter-text-parser ライブラリの使用を検討
    """
    comment_length = _safe_text_length(comment)
    if comment_length <= max_length:
        return comment

    logger.warning(f"Comment too long ({comment_length} chars), truncating...")
    normalized_comment = unicodedata.normalize("NFC", comment)
    target_length = max_length - 3  # "..." を考慮
    # 超過分を一気に引いてから微調整
    truncated = normalized_comment[:target_length] + "..."
    over = _safe_text_length(truncated) - max_length
    if over > 0:
        target_length = max(0, target_length - over)
        truncated = normalized_comment[:target_length] + "..."
    # 微調整ループ（target_lengthを減らせば_safe_text_length(truncated)も減るため、必ず終了する）
    while _safe_text_length(truncated) > max_length and target_length > 0:
        target_length -= 1
        truncated = normalized_comment[:target_length] + "..."
    return truncated


# 本文末尾のURL（疑似引用リツイートの "コメント + 半角スペース + URL" 構造を想定）を検出するパターン
_TRAILING_URL_PATTERN = re.compile(r"(https?://\S+)$")


def _truncate_text_preserving_trailing_url(text: str, max_length: int) -> str:
    """
    文字数超過時に、末尾のURLを壊さずに本文（コメント部分）側を切り詰める

    pseudo_quote_tweet()のコメント文字数バジェット（MAX_QUOTE_COMMENT_LENGTH）は
    Twitterのt.co短縮後のURL長（約23文字）を前提にしているが、post_tweet()側の
    文字数チェックは短縮前の生のURL（x.com/{username}/status/{tweet_id}、
    40〜60文字程度）を含めた全体の長さで行われる。そのため「コメント＋URL」の
    合計が280文字を超えるケースがあり、単純に末尾を切り詰めるとURL自体が
    途中で切れて壊れたリンクになってしまう。これを防ぐため、末尾にURLがある
    場合はURLを保護し、それより前の本文側だけを切り詰める。

    Args:
        text: 切り詰め対象のテキスト
        max_length: 最大文字数

    Returns:
        URLを保護しつつ切り詰めたテキスト（末尾にURLが無い場合は従来通り単純に切り詰める）
    """
    match = _TRAILING_URL_PATTERN.search(text)
    if not match:
        # URLを含まない場合は本文全体をUnicode安全に切り詰める
        return _truncate_comment(text, max_length)

    url = match.group(1)
    prefix = text[: match.start()].rstrip()

    url_length = _safe_text_length(url)
    if url_length >= max_length:
        # URL単体で上限を超える異常系。これ以上安全に切り詰められないため、
        # 警告のみでそのまま返す（Twitter API側でエラーになる可能性がある）
        logger.error(f"URL alone exceeds max tweet length ({url_length} > {max_length}); returning text as-is")
        return text

    # URLとの区切りスペース1文字分を確保した上で、本文側に使える文字数を計算
    available_for_prefix = max_length - url_length - 1
    truncated_prefix = _truncate_comment(prefix, available_for_prefix)

    return f"{truncated_prefix} {url}"


# ログ設定
# ロギングの基本設定（ハンドラ・フォーマット）はエントリポイント（main.py）側で行う。
# ライブラリ側のモジュールでlogging.basicConfig()を呼ぶと、最初に呼ばれた設定だけが
# 有効になるPythonの仕様上、import順序次第でmain.py側のフォーマット設定が
# 無効化されてしまうため、ここではLoggerの取得のみを行う。
logger = logging.getLogger(__name__)


class TwitterClient:
    """Twitter API クライアント"""

    def __init__(self, dry_run: bool = False) -> None:
        """Twitter APIクライアントを初期化"""
        self.dry_run = dry_run
        self.client = None
        self.api = None
        if not dry_run:
            self._setup_client()
        else:
            logger.info(f"🎭 {BOT_NAME} Twitter client initialized in DRY RUN mode")

    def _setup_client(self) -> None:
        """Twitter APIクライアントをセットアップ"""
        try:
            # Twitter API v2 クライアント（投稿・タイムライン取得はOAuth 1.0aユーザーコンテキストを使用）
            # 検索(search_recent_tweets)はOAuth 1.0aでは401になり、Bearerトークンによる
            # App-only認証（呼び出し側でuser_auth=Falseを指定）でのみ許可されるため、
            # bearer_tokenも併せて渡しておく（実機確認済み、2026-08-29）
            self.client = tweepy.Client(
                bearer_token=TWITTER_BEARER_TOKEN,
                consumer_key=TWITTER_API_KEY,
                consumer_secret=TWITTER_API_SECRET,
                access_token=TWITTER_ACCESS_TOKEN,
                access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
                wait_on_rate_limit=True,
            )

            # Twitter API v1.1 （画像投稿などに必要な場合）
            auth = tweepy.OAuth1UserHandler(
                TWITTER_API_KEY,
                TWITTER_API_SECRET,
                TWITTER_ACCESS_TOKEN,
                TWITTER_ACCESS_TOKEN_SECRET,
            )
            self.api = tweepy.API(auth, wait_on_rate_limit=True)

            logger.info(f"✅ {BOT_NAME} Twitter client initialized successfully")

        except Exception as e:
            logger.error(f"❌ Twitter client initialization failed: {e}")
            raise

    def test_connection(self) -> bool:
        """API接続テスト"""
        if self.dry_run:
            logger.info("🎭 [DRY RUN] Simulating connection test - SUCCESS")
            return True

        try:
            if self.client is None:
                logger.error("❌ Twitter client not initialized")
                return False

            # 自分のユーザー情報を取得してテスト
            me = self.client.get_me()
            logger.info(f"✅ Connection test successful! Account: @{me.data.username}")
            return True

        except Exception as e:
            logger.error(f"❌ Connection test failed: {e}")
            return False

    def post_tweet(self, text: str) -> Optional[str]:
        """ツイートを投稿"""
        if self.dry_run:
            logger.info(f"🎭 [DRY RUN] Would post tweet: {text}")
            return "mock_tweet_id"

        try:
            if self.client is None:
                logger.error("❌ Twitter client not initialized")
                return None

            # 文字数チェック（280文字制限、Unicode安全カウントを使用）
            # 末尾にURLを含む場合（疑似引用リツイート等）はURLを壊さないよう保護しつつ
            # 本文側だけを切り詰める（_truncate_text_preserving_trailing_url参照）
            text_length = _safe_text_length(text)
            if text_length > 280:
                logger.warning(f"Tweet too long ({text_length} chars), truncating...")
                text = _truncate_text_preserving_trailing_url(text, 280)

            # ツイート投稿
            response = self.client.create_tweet(text=text)
            tweet_id = response.data["id"]

            logger.info(f"✅ Tweet posted successfully! ID: {tweet_id}")
            logger.info(f"📝 Content: {text}")

            return tweet_id

        except Exception as e:
            logger.error(f"❌ Failed to post tweet: {e}")
            return None

    def retweet(self, tweet_id: str) -> bool:
        """指定されたツイートをリツイート"""
        try:
            if self.client is None:
                logger.error("❌ Twitter client not initialized")
                return False

            self.client.retweet(tweet_id)
            logger.info(f"✅ Retweeted successfully! Tweet ID: {tweet_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to retweet: {e}")
            return False

    def like_tweet(self, tweet_id: str) -> bool:
        """指定されたツイートをいいね"""
        try:
            if self.client is None:
                logger.error("❌ Twitter client not initialized")
                return False

            self.client.like(tweet_id)
            logger.info(f"✅ Liked successfully! Tweet ID: {tweet_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to like tweet: {e}")
            return False

    def pseudo_quote_tweet(self, tweet_id: str, author_username: Optional[str], comment: str) -> Optional[str]:
        """
        コメント＋対象ツイートURLを本文に含めて投稿する（疑似引用リツイート）

        X API v2の quote_tweet_id パラメータによる引用ポストは、2026-04-20付で
        セルフサーブ全層（Free/Basic/Pro/Pay-Per-Use）から削除され、自分がメンション/
        引用された投稿にしか使えなくなった（403 Forbidden、2026-08-29実機確認済み）。
        代わりに、対象ツイートのURLを本文に含めて通常投稿すると、Xが自動でリンクカードを
        展開し、見た目上ネイティブ引用ポストとほぼ同等の表示になる（同日、Web投稿・API投稿
        の両方で実機確認済み）ため、この方式を用いる。

        Args:
            tweet_id: 引用対象のツイートID
            author_username: 引用対象ツイートの投稿者スクリーンネーム（URL組み立てに必須）
            comment: nikuneのコメント文言

        Returns:
            投稿されたツイートのID（失敗時はNone）
        """
        if not author_username:
            logger.error("❌ Cannot build pseudo quote tweet: author_username is missing")
            return None

        comment = _truncate_comment(comment, MAX_QUOTE_COMMENT_LENGTH)
        url = f"https://x.com/{author_username}/status/{tweet_id}"
        text = f"{comment} {url}"

        posted_id = self.post_tweet(text)
        if posted_id:
            logger.info(f"🔗 Pseudo quote of original tweet: {tweet_id}")
        return posted_id

    @staticmethod
    def _wrap_tweets_with_author_username(tweets_response: Any) -> List[Any]:
        """
        expansions=author_id付きレスポンスから、author_username付きの軽量オブジェクトに
        ラップして返す

        Note:
            tweepy.Tweetは__slots__を使用しており動的な属性追加ができないため、
            SimpleNamespaceに詰め替える。
        """
        users = (tweets_response.includes or {}).get("users") or []
        users_by_id = {user.id: user.username for user in users}
        return [
            SimpleNamespace(
                id=tweet.id,
                text=tweet.text,
                author_id=tweet.author_id,
                author_username=users_by_id.get(tweet.author_id),
                created_at=getattr(tweet, "created_at", None),
                public_metrics=getattr(tweet, "public_metrics", None),
            )
            for tweet in tweets_response.data
        ]

    def get_home_timeline(self, max_results: int = 10) -> Optional[List[Any]]:
        """フォロー中ユーザーのタイムライン取得"""
        if self.dry_run:
            logger.info(f"🎭 [DRY RUN] Would fetch {max_results} tweets from timeline")
            return None  # AutoQuoteRetweeterでモックデータを使用

        try:
            if self.client is None:
                logger.error("❌ Twitter client not initialized")
                return None

            # タイムライン取得（引用URL組み立て用にauthor_usernameも取得）
            tweets = self.client.get_home_timeline(
                max_results=max_results,
                tweet_fields=["created_at", "author_id", "text", "public_metrics"],
                expansions=["author_id"],
                user_fields=["username"],
            )

            if tweets.data:
                wrapped = self._wrap_tweets_with_author_username(tweets)
                logger.info(f"✅ Retrieved {len(wrapped)} tweets from timeline")
                return wrapped
            else:
                logger.info("📭 No tweets found in timeline")
                return []

        except Exception as e:
            logger.error(f"❌ Failed to get home timeline: {e}")
            return None

    def search_recent_food_tweets(self, query: str, max_results: int = 10) -> Optional[List[Any]]:
        """
        キーワード検索で直近ツイートを取得する（フォロー関係に依存しない候補探索）

        フォロー中タイムラインだけでは候補が少なすぎる場合の補完手段。
        検索(search_recent_tweets)はOAuth 1.0aユーザーコンテキストでは401になり、
        Bearerトークンによるapp-only認証（user_auth=False）でのみ許可される
        （2026-08-29実機確認済み）。

        Args:
            query: X検索クエリ（例: "(肉 OR グルメ) -is:retweet lang:ja"）
            max_results: 取得件数

        Returns:
            マッチしたツイートのリスト（失敗時はNone）
        """
        if self.dry_run:
            logger.info(f"🎭 [DRY RUN] Would search recent tweets: {query}")
            return None  # AutoQuoteRetweeterでモックデータを使用

        try:
            if self.client is None:
                logger.error("❌ Twitter client not initialized")
                return None

            tweets = self.client.search_recent_tweets(
                query=query,
                max_results=max_results,
                tweet_fields=["created_at", "author_id", "text", "public_metrics"],
                expansions=["author_id"],
                user_fields=["username"],
                user_auth=False,
            )

            if tweets.data:
                wrapped = self._wrap_tweets_with_author_username(tweets)
                logger.info(f"✅ Retrieved {len(wrapped)} tweets from search")
                return wrapped
            else:
                logger.info("📭 No tweets found in search")
                return []

        except Exception as e:
            logger.error(f"❌ Failed to search recent tweets: {e}")
            return None


# テスト用関数
def test_twitter_client(dry_run: bool = True) -> None:
    """Twitter クライアントのテスト実行"""
    print(f"🐻 {BOT_NAME} Twitter client test starting...")

    if dry_run:
        print("🎭 Running in DRY RUN mode - no API calls will be made")
        # ドライランモードでクライアント作成
        client = TwitterClient(dry_run=True)

        # ドライランでの基本テスト
        print("✅ Twitter client initialized in dry run mode")
        print("✅ Mock connection test passed")

        # モック投稿テスト
        test_tweet = "🐻 nikune bot test - お肉の魅力をお届けします！"
        result = client.post_tweet(test_tweet)
        if result:
            print(f"✅ Mock tweet posted: {result}")
        else:
            print("❌ Mock tweet posting failed")

    else:
        print("⚠️ Running in LIVE mode - real API calls will be made")
        # ライブモードでクライアント作成
        client = TwitterClient(dry_run=False)

        # 接続テスト
        if client.test_connection():
            print("🎉 Twitter API connection successful!")

            # テストツイート（コメントアウト推奨）
            # test_tweet = "🐻 nikune bot test - お肉の魅力をお届けします！"
            # client.post_tweet(test_tweet)

        else:
            print("❌ Twitter API connection failed!")


if __name__ == "__main__":
    test_twitter_client(dry_run=True)  # デフォルトはドライラン
