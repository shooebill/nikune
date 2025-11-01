"""
nikune bot auto quote retweeter
フォロー中ユーザーのお肉関連ツイートを自動でコメント付きリツイート
"""

import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from config.settings import (
    BOT_NAME,
    QUOTE_RETWEET_HIGH_PRIORITY_LIMIT,
    QUOTE_RETWEET_MAX_PER_HOUR,
    QUOTE_RETWEET_MIN_INTERVAL_MINUTES,
    QUOTE_RETWEET_MIN_PRIORITY_SCORE,
)
from nikune.content_generator import ContentGenerator
from nikune.database import DatabaseManager
from nikune.twitter_client import TwitterClient

# 定数定義
MAX_PROCESSED_TWEETS = 1000  # 処理済みツイートの最大追跡数
CLEANUP_WARNING_THRESHOLD = 0.9  # クリーンアップ警告の閾値
CLEANUP_WARNING_COUNT = int(
    MAX_PROCESSED_TWEETS * CLEANUP_WARNING_THRESHOLD
)  # 警告閾値（浮動小数点計算後、int変換で切り捨て, 900）

# Twitter API Rate Limit対策
API_RETRY_DELAY_SECONDS = 60  # API エラー後の待機時間（秒）
MAX_TIMELINE_FETCH_RETRIES = 2  # タイムライン取得の最大リトライ回数
API_BACKOFF_MULTIPLIER = 2  # バックオフ倍率（指数的バックオフ）

# ログ設定
logger = logging.getLogger(__name__)


class AutoQuoteRetweeter:
    """
    自動コメント付きリツイート機能

    フォロー中ユーザーのお肉関連ツイートを自動検出し、
    かわいいコメント付きで引用リツイートする機能を提供します。

    重要な制限事項:
        - 処理済みツイートの追跡はメモリ内のOrderedDictで管理されており、
          アプリケーション再起動後は履歴が失われます
        - そのため、再起動直後は過去に処理済みのツイートを重複して
          Quote Retweetする可能性があります
        - 本格運用では Redis による永続化が推奨されます（上記「重要な制限事項」参照）
    """

    def __init__(self, db_manager: DatabaseManager, dry_run: bool = False) -> None:
        """自動Quote Retweeterを初期化"""
        self.db_manager = db_manager
        self.dry_run = dry_run
        self.twitter_client = TwitterClient(dry_run=dry_run)
        self.content_generator = ContentGenerator(db_manager)
        self.bot_name = BOT_NAME

        # 処理済みツイートを追跡（重複防止）
        # OrderedDictで順序保持とO(1)検索を両立、サイズ管理も自動化
        # 永続化についてはクラスdocstringの「重要な制限事項」を参照
        self.processed_tweets: OrderedDict[str, datetime] = OrderedDict()
        self._processed_tweets_lock = threading.Lock()  # スレッドセーフティ確保

        # レート制限管理（設定から取得）
        self.last_quote_time: Optional[datetime] = None
        self.min_interval_minutes = QUOTE_RETWEET_MIN_INTERVAL_MINUTES
        self.max_quotes_per_hour = QUOTE_RETWEET_MAX_PER_HOUR
        self.quotes_in_last_hour: List[datetime] = []

        # 優先度システム設定
        self.min_priority_score = QUOTE_RETWEET_MIN_PRIORITY_SCORE
        self.high_priority_limit = QUOTE_RETWEET_HIGH_PRIORITY_LIMIT
        self.high_priority_quotes_in_hour: List[datetime] = []

        # 自分のユーザーIDをキャッシュ（遅延初期化でRate Limit対策）
        self.my_user_id: Optional[str] = None
        self._user_id_fetch_attempted: bool = False

        # 警告ログ制御フラグ（繰り返し出力防止）
        self._warning_logged: bool = False

        logger.info(f"✅ {self.bot_name} Auto Quote Retweeter initialized")
        logger.info(f"📊 Rate limits: {self.min_interval_minutes}min interval, {self.max_quotes_per_hour}/hour max")

    def _cache_my_user_id(self) -> Optional[str]:
        """初期化時に自分のユーザーIDを取得してキャッシュ"""
        try:
            if self.twitter_client.client is None:
                logger.warning("⚠️ Twitter client not available for user ID caching")
                return None

            # Rate Limit対策: get_me()が失敗してもシステムは動作するよう設計
            me = self.twitter_client.client.get_me()
            if me and me.data:
                if hasattr(me.data, "id"):
                    user_id = me.data.id
                elif isinstance(me.data, dict):
                    user_id = me.data.get("id")
                else:
                    user_id = None

                if user_id is not None:
                    user_id = str(user_id)
                    logger.info(f"📋 Cached user ID: {user_id}")
                    return user_id
                else:
                    logger.warning("⚠️ User ID not found in response data")
                    return None
            return None
        except Exception as e:
            # Rate Limitエラーなどが発生した場合も警告のみで続行
            logger.warning(f"⚠️ Failed to cache user ID (possibly rate limited): {e}")
            logger.info("📝 System will continue without user ID caching (自分のツイート除外は無効化)")
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
            if dry_run or self.dry_run:
                timeline_tweets = self._get_mock_timeline()
                logger.info("🎭 Using mock timeline data for dry run")
            else:
                fetched_tweets = self._fetch_timeline_with_retry()
                if fetched_tweets is None:
                    # リトライ後も失敗した場合
                    results["success"] = True
                    results["errors"].append("Timeline fetch failed after retries")
                    return results
                timeline_tweets = fetched_tweets

            if not timeline_tweets:
                logger.info("📭 No tweets found in timeline")
                results["success"] = True
                return results

            results["checked_tweets"] = len(timeline_tweets)
            logger.info(f"🔍 Checking {len(timeline_tweets)} tweets from timeline")

            # 各ツイートをチェック
            skipped_processed = 0
            for tweet in timeline_tweets:
                try:
                    # 既に処理済みかチェック（OrderedDictでO(1)検索・スレッドセーフ）
                    with self._processed_tweets_lock:
                        if tweet.id in self.processed_tweets:
                            skipped_processed += 1
                            logger.debug(f"⏭️ Already processed tweet: {tweet.id}")
                            continue

                    # 自分のツイートは除外
                    if self._is_own_tweet(tweet):
                        continue

                    # お肉関連ツイートかチェック（優先度スコアリング対応）
                    score_info = self.content_generator.get_meat_keyword_score(tweet.text)

                    if score_info["is_meat_related"]:
                        results["meat_related_found"] += 1
                        priority_level = score_info["highest_priority_level"]
                        score = score_info["score"]
                        keywords = score_info["matched_keywords"]

                        logger.info(f"🥩 Found meat-related tweet: {tweet.id}")
                        logger.info(f"� Priority: {priority_level} (Score: {score})")
                        logger.info(f"🔍 Keywords: {keywords}")
                        logger.info(f"�📝 Content: {tweet.text[:100]}...")

                        # 優先度フィルタリング
                        if score < self.min_priority_score:
                            logger.info(f"⏭️ Skipping low priority tweet (Score: {score} < {self.min_priority_score})")
                            continue

                        # 高優先度ツイートのレート制限チェック
                        if score >= 3 and not self._can_quote_high_priority():
                            logger.info(f"⏰ High priority rate limit reached, skipping tweet (Score: {score})")
                            continue

                        # コメント生成（優先度対応版）
                        comment = self.content_generator.generate_quote_comment(tweet.text)

                        if dry_run or self.dry_run:
                            logger.info(f"🔄 [DRY RUN] Would quote tweet with comment: {comment}")
                        else:
                            # Quote Tweet実行
                            quote_id = self.twitter_client.quote_tweet(tweet.id, comment)
                            if quote_id:
                                results["quote_posted"] += 1
                                self.last_quote_time = datetime.now()
                                self.quotes_in_last_hour.append(self.last_quote_time)

                                # 高優先度ツイートの記録
                                if score >= 3:
                                    self.high_priority_quotes_in_hour.append(self.last_quote_time)

                                logger.info(f"✅ Successfully posted quote tweet: {quote_id}")

                        # 処理済みとしてマーク（OrderedDictに処理時刻と共に記録・スレッドセーフ）
                        with self._processed_tweets_lock:
                            self.processed_tweets[tweet.id] = datetime.now()
                        self._cleanup_old_processed_tweets()

                        # 優先度の高いツイートはすぐに処理、低いものは条件によりスキップ
                        if score >= 3:  # HIGH priority
                            logger.info("🎯 High priority tweet processed - continuing search for more")
                            # 高優先度の場合は処理後も続行（次のツイートもチェック）
                        else:
                            # 中・低優先度の場合は1件処理したら終了（従来通り）
                            break

                except Exception as e:
                    error_msg = f"Error processing tweet {tweet.id}: {e}"
                    logger.error(f"❌ {error_msg}")
                    results["errors"].append(error_msg)

            results["skipped_already_processed"] = skipped_processed
            results["success"] = True

            # 処理結果のサマリーログ
            if skipped_processed > 0:
                logger.info(f"📊 Skipped {skipped_processed} already processed tweets")

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

    def _can_quote_high_priority(self) -> bool:
        """高優先度Quote Tweetが可能かどうかチェック"""
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        # 高優先度ツイートの履歴をクリーンアップ
        self.high_priority_quotes_in_hour = [qt for qt in self.high_priority_quotes_in_hour if qt > one_hour_ago]

        return len(self.high_priority_quotes_in_hour) < self.high_priority_limit

    def _fetch_timeline_with_retry(self) -> Optional[List[Any]]:
        """リトライ機能付きタイムライン取得（指数的バックオフ）"""
        max_retries = MAX_TIMELINE_FETCH_RETRIES
        base_delay = API_RETRY_DELAY_SECONDS

        for attempt in range(max_retries + 1):
            try:
                timeline_tweets = self.twitter_client.get_home_timeline(max_results=20)
                if timeline_tweets is not None:
                    return timeline_tweets

                logger.warning(f"⚠️ Timeline fetch returned None (attempt {attempt + 1}/{max_retries + 1})")

            except Exception as e:
                error_msg = f"Timeline fetch error (attempt {attempt + 1}/{max_retries + 1}): {e}"
                logger.warning(f"⚠️ {error_msg}")

                if attempt < max_retries:
                    # 指数的バックオフで待機
                    delay = base_delay * (API_BACKOFF_MULTIPLIER**attempt)
                    logger.info(f"⏰ Retrying after {delay} seconds...")
                    time.sleep(delay)
                else:
                    logger.error(f"❌ Timeline fetch failed after {max_retries + 1} attempts")
                    return None

        return None

    def _is_own_tweet(self, tweet: Any) -> bool:
        """自分のツイートかどうかチェック（遅延初期化でRate Limit対策）"""
        try:
            # ドライランモードの場合は自分のツイート判定をスキップ
            if self.dry_run:
                logger.debug("🎭 Dry run mode: skipping own tweet check")
                return False

            # 遅延初期化: 必要な時のみユーザーIDを取得
            if self.my_user_id is None and not self._user_id_fetch_attempted:
                self._user_id_fetch_attempted = True
                self.my_user_id = self._cache_my_user_id()

            if self.my_user_id is None:
                # ユーザーIDが取得できない場合は自分のツイート判定をスキップ
                logger.debug("🔍 User ID unavailable, skipping own tweet check")
                return False

            # キャッシュされたユーザーIDと比較（API呼び出しなし）
            if hasattr(tweet, "author_id") and tweet.author_id is not None:
                tweet_author_id = str(tweet.author_id)
            else:
                tweet_author_id = ""
            return tweet_author_id == self.my_user_id
        except Exception:
            return False

    def _get_mock_timeline(self) -> List[Any]:
        """ドライラン用のモックタイムラインデータを生成"""
        from types import SimpleNamespace

        mock_tweets = [
            SimpleNamespace(
                id="mock_tweet_1",
                text="本日も元気いっぱい11:00よりオープンです！もうご賞味頂けましたか⁉︎数量限定でさらに肉感アップしての登場です。ランチタイムならライス＆豚汁付き是非ご賞味くださいませ。#akiba",
                author_id="mock_user_1",
                created_at="2024-10-29T10:00:00.000Z",
            ),
            SimpleNamespace(
                id="mock_tweet_2",
                text="今日は良い天気ですね〜お散歩日和です",
                author_id="mock_user_2",
                created_at="2024-10-29T09:30:00.000Z",
            ),
            SimpleNamespace(
                id="mock_tweet_3",
                text="美味しいステーキを食べました🥩とても柔らかくて最高でした！",
                author_id="mock_user_3",
                created_at="2024-10-29T09:00:00.000Z",
            ),
            SimpleNamespace(
                id="mock_tweet_4",
                text="プログラミングの勉強中です。Pythonは楽しいですね",
                author_id="mock_user_4",
                created_at="2024-10-29T08:30:00.000Z",
            ),
            SimpleNamespace(
                id="mock_tweet_5",
                text="焼肉パーティーしました🍖みんなでワイワイ楽しかった〜",
                author_id="mock_user_5",
                created_at="2024-10-29T08:00:00.000Z",
            ),
        ]

        return mock_tweets

    def _cleanup_old_processed_tweets(self) -> None:
        """古い処理済みツイートIDを削除（メモリ管理・スレッドセーフ）"""
        with self._processed_tweets_lock:
            # 上限を超えた場合、最も古いエントリから削除
            while len(self.processed_tweets) > MAX_PROCESSED_TWEETS:
                oldest_tweet_id = next(iter(self.processed_tweets))
                del self.processed_tweets[oldest_tweet_id]
                logger.debug(f"🧹 Removed old processed tweet: {oldest_tweet_id}")

            # 処理済みツイート数が上限の90%に達した場合に警告ログを出力（初回のみ）
            threshold_reached = len(self.processed_tweets) >= CLEANUP_WARNING_COUNT

        if threshold_reached and not self._warning_logged:
            count = len(self.processed_tweets)
            logger.warning(f"⚠️ Processed tweets approaching limit: {count}/{MAX_PROCESSED_TWEETS}")
            self._warning_logged = True
        elif not threshold_reached and self._warning_logged:
            # 閾値を下回った場合はフラグをリセット
            self._warning_logged = False

    def cleanup_old_processed_tweets(self) -> None:
        """パブリックなクリーンアップメソッド（後方互換性）"""
        self._cleanup_old_processed_tweets()

    def get_status(self) -> Dict[str, Any]:
        """現在のステータス情報を取得"""
        can_quote = self._can_quote_now()

        next_available = None
        if not can_quote:
            now = datetime.now()
            # 最小間隔制限の解除時刻
            min_interval_time = None
            if self.last_quote_time:
                min_interval_time = self.last_quote_time + timedelta(minutes=self.min_interval_minutes)

            # 1時間制限の解除時刻
            hour_limit_time = None
            if (
                hasattr(self, "quotes_in_last_hour")
                and self.quotes_in_last_hour
                and len(self.quotes_in_last_hour) >= self.max_quotes_per_hour
            ):
                oldest_quote_time = self.quotes_in_last_hour[0]
                hour_limit_time = oldest_quote_time + timedelta(hours=1)

            # 解除時刻候補のうち、未来のもののみを比較
            candidates = [t for t in [min_interval_time, hour_limit_time] if t and t > now]
            if candidates:
                next_available = max(candidates)

        return {
            "can_quote_now": can_quote,
            "last_quote_time": self.last_quote_time.isoformat() if self.last_quote_time else None,
            "next_available_time": next_available.isoformat() if next_available else None,
            "processed_tweets_count": len(self.processed_tweets),
            "quotes_in_last_hour": len(self.quotes_in_last_hour),
            "max_quotes_per_hour": self.max_quotes_per_hour,
            "min_interval_minutes": self.min_interval_minutes,
            "priority_system": {
                "min_priority_score": self.min_priority_score,
                "high_priority_limit": self.high_priority_limit,
                "high_priority_quotes_in_hour": len(self.high_priority_quotes_in_hour),
                "can_quote_high_priority": self._can_quote_high_priority(),
            },
        }


# テスト用関数
def test_auto_quote_retweeter(dry_run: bool = True) -> None:
    """Auto Quote Retweeter のテスト実行"""
    print(f"🐻 {BOT_NAME} Auto Quote Retweeter test starting...")

    try:
        # データベース接続
        with DatabaseManager() as db_manager:
            # Auto Quote Retweeter 作成（ドライランモード対応）
            retweeter = AutoQuoteRetweeter(db_manager, dry_run=dry_run)

            if dry_run:
                print("🎭 Running in DRY RUN mode")
            else:
                print("⚠️ Running in LIVE mode")

            # ステータス表示
            status = retweeter.get_status()
            print(f"📊 Status: {status}")

            # テスト実行
            print("🔄 Running test...")
            results = retweeter.check_and_quote_tweets(dry_run=dry_run)
            print(f"✅ Test results: {results}")

    except Exception as e:
        print(f"❌ Test failed: {e}")


if __name__ == "__main__":
    test_auto_quote_retweeter(dry_run=True)  # デフォルトはドライラン
