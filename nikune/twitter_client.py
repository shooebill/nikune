"""
nikune bot Twitter API client
Twitter APIとの接続、ツイート投稿などを担当
"""

import logging
from typing import Optional

import tweepy

from config.settings import (
    BOT_NAME,
    TWITTER_ACCESS_TOKEN,
    TWITTER_ACCESS_TOKEN_SECRET,
    TWITTER_API_KEY,
    TWITTER_API_SECRET,
)

# 定数定義
MAX_QUOTE_COMMENT_LENGTH = 250  # Quote comment の最大文字数（Twitter280文字制限から引用URL約23文字を考慮）

# ログ設定
logging.basicConfig(level=logging.INFO)
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
            # Twitter API v2 クライアント（ツイート投稿用）
            self.client = tweepy.Client(
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

            # 文字数チェック（280文字制限）
            if len(text) > 280:
                logger.warning(f"Tweet too long ({len(text)} chars), truncating...")
                text = text[:277] + "..."

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

    def quote_tweet(self, tweet_id: str, comment: str) -> Optional[str]:
        """コメント付きリツイート（Quote Tweet）"""
        if self.dry_run:
            logger.info(f"🎭 [DRY RUN] Would quote tweet {tweet_id} with comment: {comment}")
            return "mock_quote_tweet_id"

        try:
            if self.client is None:
                logger.error("❌ Twitter client not initialized")
                return None

            # 文字数チェック（280文字制限 - 引用分を考慮）
            # TODO: より正確な文字数カウントのため twitter-text-parser ライブラリの使用を検討
            # 現在のlen()はUnicodeコードポイント単位だが、Twitterのカウントとは異なる場合がある
            # 特に絵文字や結合文字を含む場合は注意が必要
            if len(comment) > MAX_QUOTE_COMMENT_LENGTH:  # 引用URLを考慮して短めに設定
                logger.warning(f"Comment too long ({len(comment)} chars), truncating...")
                comment = comment[:MAX_QUOTE_COMMENT_LENGTH - 3] + "..."  # fmt: skip

            # コメント付きリツイート実行
            response = self.client.create_tweet(text=comment, quote_tweet_id=tweet_id)
            quote_tweet_id = response.data["id"]

            logger.info(f"✅ Quote tweet posted successfully! ID: {quote_tweet_id}")
            logger.info(f"📝 Comment: {comment}")
            logger.info(f"🔗 Original tweet ID: {tweet_id}")

            return quote_tweet_id

        except Exception as e:
            logger.error(f"❌ Failed to quote tweet: {e}")
            return None

    def get_home_timeline(self, max_results: int = 10) -> Optional[list]:
        """フォロー中ユーザーのタイムライン取得"""
        if self.dry_run:
            logger.info(f"🎭 [DRY RUN] Would fetch {max_results} tweets from timeline")
            return None  # AutoQuoteRetweeterでモックデータを使用

        try:
            if self.client is None:
                logger.error("❌ Twitter client not initialized")
                return None

            # タイムライン取得
            tweets = self.client.get_home_timeline(
                max_results=max_results, tweet_fields=["created_at", "author_id", "text", "public_metrics"]
            )

            if tweets.data:
                logger.info(f"✅ Retrieved {len(tweets.data)} tweets from timeline")
                return tweets.data
            else:
                logger.info("📭 No tweets found in timeline")
                return []

        except Exception as e:
            logger.error(f"❌ Failed to get home timeline: {e}")
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
