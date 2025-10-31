"""
nikune bot auto quote retweeter
フォロー中ユーザーのお肉関連ツイートを自動でコメント付きリツイート
"""

import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from config.settings import (
    BOT_NAME,
    QUOTE_RETWEET_MAX_PER_HOUR,
    QUOTE_RETWEET_MIN_INTERVAL_MINUTES,
)
from nikune.content_generator import ContentGenerator
from nikune.database import DatabaseManager
from nikune.twitter_client import TwitterClient

# 定数定義
MAX_PROCESSED_TWEETS = 1000  # 処理済みツイートの最大追跡数
CLEANUP_WARNING_THRESHOLD = 0.9  # クリーンアップ警告の閾値

# ログ設定
logger = logging.getLogger(__name__)


class AutoQuoteRetweeter:
    """自動コメント付きリツイート機能"""

    def __init__(self, db_manager: DatabaseManager) -> None:
        """自動Quote Retweeterを初期化"""
        self.db_manager = db_manager
        self.twitter_client = TwitterClient()
        self.content_generator = ContentGenerator(db_manager)
        self.bot_name = BOT_NAME

        # 処理済みツイートを追跡（重複防止）
        # OrderedDictで順序保持とO(1)検索を両立、サイズ管理も自動化
        # TODO: これは redis で管理したい - アプリ再起動後も処理済み履歴を永続化
        self.processed_tweets: OrderedDict[str, datetime] = OrderedDict()

        # レート制限管理（設定から取得）
        self.last_quote_time: Optional[datetime] = None
        self.min_interval_minutes = QUOTE_RETWEET_MIN_INTERVAL_MINUTES
        self.max_quotes_per_hour = QUOTE_RETWEET_MAX_PER_HOUR
        self.quotes_in_last_hour: List[datetime] = []

        # 自分のユーザーIDをキャッシュ（API呼び出し最適化）
        self.my_user_id: Optional[str] = self._cache_my_user_id()

        # 警告ログ制御フラグ（繰り返し出力防止）
        self._warning_logged: bool = False

        logger.info(f"✅ {self.bot_name} Auto Quote Retweeter initialized")
        logger.info(f"📊 Rate limits: {self.min_interval_minutes}min interval, " f"{self.max_quotes_per_hour}/hour max")

    def _cache_my_user_id(self) -> Optional[str]:
        """初期化時に自分のユーザーIDを取得してキャッシュ"""
        try:
            if self.twitter_client.client is None:
                logger.warning("⚠️ Twitter client not available for user ID caching")
                return None
            me = self.twitter_client.client.get_me()
            if me and me.data:
                user_id = str(getattr(me.data, "id", ""))
                logger.info(f"📋 Cached user ID: {user_id}")
                return user_id
            return None
        except Exception as e:
            logger.warning(f"⚠️ Failed to cache user ID: {e}")
            return None

    def check_and_quote_tweets(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        タイムラインをチェックしてお肉関連ツイートをQuote Retweet

        Args:
            dry_run: True の場合、実際には投稿せずにログ出力のみ

        Returns:
            実行結果の辞書
        """
        try:
            results: Dict[str, Any] = {
                "success": False,
                "checked_tweets": 0,
                "meat_related_found": 0,
                "quote_posted": 0,
                "skipped_rate_limit": 0,
                "errors": [],
            }

            # レート制限チェック
            if not self._can_quote_now():
                logger.info("⏰ Rate limit: skipping quote retweet check")
                results["skipped_rate_limit"] = 1
                results["success"] = True
                return results

            # タイムライン取得（ドライラン時はモックデータ使用）
            if dry_run:
                timeline_tweets = self._get_mock_timeline()
                logger.info("🎭 Using mock timeline data for dry run")
            else:
                timeline_tweets = self.twitter_client.get_home_timeline(max_results=20) or []

            if not timeline_tweets:
                logger.info("📭 No tweets found in timeline")
                results["success"] = True
                return results

            results["checked_tweets"] = len(timeline_tweets)
            logger.info(f"🔍 Checking {len(timeline_tweets)} tweets from timeline")

            # 各ツイートをチェック
            for tweet in timeline_tweets:
                try:
                    # 既に処理済みかチェック（OrderedDictでO(1)検索）
                    if tweet.id in self.processed_tweets:
                        continue

                    # 自分のツイートは除外
                    if self._is_own_tweet(tweet):
                        continue

                    # お肉関連ツイートかチェック
                    if self.content_generator.is_meat_related_tweet(tweet.text):
                        results["meat_related_found"] += 1
                        logger.info(f"🥩 Found meat-related tweet: {tweet.id}")
                        logger.info(f"📝 Content: {tweet.text[:100]}...")

                        # コメント生成
                        comment = self.content_generator.generate_quote_comment(tweet.text)

                        if dry_run:
                            logger.info(f"🔄 [DRY RUN] Would quote tweet with comment: {comment}")
                        else:
                            # Quote Tweet実行
                            quote_id = self.twitter_client.quote_tweet(tweet.id, comment)
                            if quote_id:
                                results["quote_posted"] += 1
                                self.last_quote_time = datetime.now()
                                self.quotes_in_last_hour.append(self.last_quote_time)
                                logger.info(f"✅ Successfully posted quote tweet: {quote_id}")

                        # 処理済みとしてマーク（OrderedDictに処理時刻と共に記録）
                        self.processed_tweets[tweet.id] = datetime.now()
                        self._cleanup_old_processed_tweets()

                        # 1回の実行で1件のみ処理（スパム防止）
                        break

                except Exception as e:
                    error_msg = f"Error processing tweet {tweet.id}: {e}"
                    logger.error(f"❌ {error_msg}")
                    results["errors"].append(error_msg)

            results["success"] = True
            return results

        except Exception as e:
            error_msg = f"Error in check_and_quote_tweets: {e}"
            logger.error(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}

    def _can_quote_now(self) -> bool:
        """現在Quote Tweetが可能かどうかチェック"""
        now = datetime.now()

        # 最小間隔チェック
        if self.last_quote_time:
            time_since_last = now - self.last_quote_time
            if time_since_last < timedelta(minutes=self.min_interval_minutes):
                return False

        # 1時間あたりの制限チェック
        one_hour_ago = now - timedelta(hours=1)
        self.quotes_in_last_hour = [qt for qt in self.quotes_in_last_hour if qt > one_hour_ago]

        return len(self.quotes_in_last_hour) < self.max_quotes_per_hour

    def _is_own_tweet(self, tweet: Any) -> bool:
        """自分のツイートかどうかチェック（キャッシュされたIDを使用）"""
        try:
            if self.my_user_id is None:
                return False
            # キャッシュされたユーザーIDと比較（API呼び出しなし）
            tweet_author_id = str(getattr(tweet, "author_id", ""))
            return tweet_author_id == self.my_user_id
        except Exception:
            return False

    def _get_mock_timeline(self) -> List[Any]:
        """ドライラン用のモックタイムラインデータを生成"""
        from types import SimpleNamespace

        mock_tweets = [
            SimpleNamespace(
                id="mock_tweet_1",
                text="本日も元気いっぱい11:00よりオープンです！もうご賞味頂けましたか⁉︎数量限定でさらに肉感アップしての登場です。ランチタイムならライス＆豚汁付き是非ご賞味くださいまんせい。#akiba",
                author_id="mock_user_1",
                created_at="2025-10-29T10:00:00.000Z",
            ),
            SimpleNamespace(
                id="mock_tweet_2",
                text="今日は良い天気ですね〜お散歩日和です",
                author_id="mock_user_2",
                created_at="2025-10-29T09:30:00.000Z",
            ),
            SimpleNamespace(
                id="mock_tweet_3",
                text="美味しいステーキを食べました🥩とても柔らかくて最高でした！",
                author_id="mock_user_3",
                created_at="2025-10-29T09:00:00.000Z",
            ),
            SimpleNamespace(
                id="mock_tweet_4",
                text="プログラミングの勉強中です。Pythonは楽しいですね",
                author_id="mock_user_4",
                created_at="2025-10-29T08:30:00.000Z",
            ),
            SimpleNamespace(
                id="mock_tweet_5",
                text="焼肉パーティーしました🍖みんなでワイワイ楽しかった〜",
                author_id="mock_user_5",
                created_at="2025-10-29T08:00:00.000Z",
            ),
        ]

        return mock_tweets

    def _cleanup_old_processed_tweets(self) -> None:
        """古い処理済みツイートIDを削除（メモリ管理）"""
        # 上限を超えた場合、最も古いエントリから削除
        while len(self.processed_tweets) > MAX_PROCESSED_TWEETS:
            oldest_tweet_id = next(iter(self.processed_tweets))
            del self.processed_tweets[oldest_tweet_id]
            logger.debug(f"🧹 Removed old processed tweet: {oldest_tweet_id}")

        # 処理済みツイート数が上限の90%に達した場合に警告ログを出力（初回のみ）
        threshold_reached = len(self.processed_tweets) >= MAX_PROCESSED_TWEETS * CLEANUP_WARNING_THRESHOLD
        if threshold_reached and not self._warning_logged:
            count = len(self.processed_tweets)
            logger.warning(f"⚠️ Processed tweets approaching limit: {count}/{MAX_PROCESSED_TWEETS}")
            self._warning_logged = True

    def cleanup_old_processed_tweets(self) -> None:
        """パブリックなクリーンアップメソッド（後方互換性）"""
        self._cleanup_old_processed_tweets()

    def get_status(self) -> Dict[str, Any]:
        """現在のステータス情報を取得"""
        can_quote = self._can_quote_now()

        next_available = None
        if self.last_quote_time and not can_quote:
            next_available = self.last_quote_time + timedelta(minutes=self.min_interval_minutes)

        return {
            "can_quote_now": can_quote,
            "last_quote_time": self.last_quote_time.isoformat() if self.last_quote_time else None,
            "next_available_time": next_available.isoformat() if next_available else None,
            "processed_tweets_count": len(self.processed_tweets),
            "quotes_in_last_hour": len(self.quotes_in_last_hour),
            "max_quotes_per_hour": self.max_quotes_per_hour,
            "min_interval_minutes": self.min_interval_minutes,
        }


# テスト用関数
def test_auto_quote_retweeter() -> None:
    """Auto Quote Retweeter のテスト実行"""
    print(f"🐻 {BOT_NAME} Auto Quote Retweeter test starting...")

    try:
        # データベース接続
        with DatabaseManager() as db_manager:
            # Auto Quote Retweeter 作成
            retweeter = AutoQuoteRetweeter(db_manager)

            # ステータス表示
            status = retweeter.get_status()
            print(f"📊 Status: {status}")

            # ドライランテスト
            print("🔄 Running dry run test...")
            results = retweeter.check_and_quote_tweets(dry_run=True)
            print(f"✅ Test results: {results}")

    except Exception as e:
        print(f"❌ Test failed: {e}")


if __name__ == "__main__":
    test_auto_quote_retweeter()
