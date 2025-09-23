"""
nikune bot Twitter API client
Twitter APIとの接続、ツイート投稿などを担当
"""

import logging

import tweepy

from config.settings import (
    BOT_NAME,
    TWITTER_ACCESS_TOKEN,
    TWITTER_ACCESS_TOKEN_SECRET,
    TWITTER_API_KEY,
    TWITTER_API_SECRET,
)

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TwitterClient:
    """Twitter API クライアント"""

    def __init__(self):
        """Twitter APIクライアントを初期化"""
        self.client = None
        self.api = None
        self._setup_client()

    def _setup_client(self):
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

    def test_connection(self):
        """API接続テスト"""
        try:
            # 自分のユーザー情報を取得してテスト
            me = self.client.get_me()
            logger.info(f"✅ Connection test successful! Account: @{me.data.username}")
            return True

        except Exception as e:
            logger.error(f"❌ Connection test failed: {e}")
            return False

    def post_tweet(self, text):
        """ツイートを投稿"""
        try:
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

    def retweet(self, tweet_id):
        """指定されたツイートをリツイート"""
        try:
            self.client.retweet(tweet_id)
            logger.info(f"✅ Retweeted successfully! Tweet ID: {tweet_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to retweet: {e}")
            return False

    def like_tweet(self, tweet_id):
        """指定されたツイートをいいね"""
        try:
            self.client.like(tweet_id)
            logger.info(f"✅ Liked successfully! Tweet ID: {tweet_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to like tweet: {e}")
            return False


# テスト用関数
def test_twitter_client():
    """Twitter クライアントのテスト実行"""
    print(f"🐻 {BOT_NAME} Twitter client test starting...")

    # クライアント作成
    client = TwitterClient()

    # 接続テスト
    if client.test_connection():
        print("🎉 Twitter API connection successful!")

        # テストツイート（コメントアウト推奨）
        # test_tweet = "🐻 nikune bot test - お肉の魅力をお届けします！"
        # client.post_tweet(test_tweet)

    else:
        print("❌ Twitter API connection failed!")


if __name__ == "__main__":
    test_twitter_client()
