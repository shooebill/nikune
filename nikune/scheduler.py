"""
Nikune Twitter Bot - スケジューラーモジュール

定期的なツイート投稿を管理するスケジューラー機能を提供します。
"""

import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional

import schedule

from config.settings import BOT_NAME
from nikune.auto_quote_retweeter import AutoQuoteRetweeter
from nikune.content_generator import ContentGenerator
from nikune.database import DatabaseManager
from nikune.twitter_client import TwitterClient
from nikune.utils import log_errors

# 定数定義
MAX_ERRORS_TO_DISPLAY = 3  # 表示するエラーの最大数
MAINTENANCE_TASKS_COUNT = 1  # 現在のメンテナンスタスク数

# ロガー設定
logger = logging.getLogger(__name__)


class SchedulerManager:
    """スケジューラー管理クラス"""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        content_generator: Optional[ContentGenerator] = None,
        twitter_client: Optional[TwitterClient] = None,
        dry_run: bool = False,
    ):
        """
        スケジューラーマネージャーを初期化

        Args:
            db_manager: データベースマネージャー（Noneの場合は新規作成）
            content_generator: コンテンツジェネレーター（Noneの場合は新規作成）
            twitter_client: Twitterクライアント（Noneの場合は新規作成）
            dry_run: ドライランモード（実際の投稿を行わない）
        """
        self.dry_run = dry_run
        self.db_manager = db_manager or DatabaseManager()
        self.content_generator = content_generator or ContentGenerator(self.db_manager)
        self.twitter_client = twitter_client or TwitterClient(dry_run=dry_run)
        self.auto_quote_retweeter = AutoQuoteRetweeter(self.db_manager, dry_run=dry_run)

        self.is_running = False
        self.scheduler_thread: Optional[threading.Thread] = None

        mode = "dry run" if dry_run else "live"
        logger.info(f"✅ {BOT_NAME} Scheduler manager initialized ({mode} mode)")

    def setup_schedule(self, schedule_config: Optional[Dict[str, Any]] = None) -> None:
        """
        投稿スケジュールを設定

        Args:
            schedule_config: スケジュール設定（Noneの場合はデフォルト設定）
        """
        try:
            # デフォルトスケジュール設定
            default_config = {
                "daily_posts": 3,
                "post_times": ["09:00", "13:30", "19:00"],
                "quote_check_times": ["10:30", "15:00", "21:00"],  # Quote Retweetチェック時間
                "categories": [
                    "お肉",
                    "日常",
                    "焼肉",
                    "ステーキ",
                    "ハンバーグ",
                    "カレー",
                    "ラーメン",
                    "グルメ",
                ],
                "random_delay": True,
                "max_delay_minutes": 15,
            }

            config: dict[str, Any] = schedule_config or default_config

            # 既存のスケジュールをクリア
            schedule.clear()

            # 投稿時間を設定
            post_times: list[str] = config.get("post_times", [])
            for post_time in post_times:
                schedule.every().day.at(post_time).do(
                    self._scheduled_post,
                    categories=config["categories"],
                    random_delay=config["random_delay"],
                    max_delay_minutes=config.get("max_delay_minutes", 15),
                )

                logger.info(f"📅 Scheduled tweet at {post_time}")

            # Quote Retweetチェック時間を設定
            quote_check_times: list[str] = config.get("quote_check_times", [])
            for quote_time in quote_check_times:
                schedule.every().day.at(quote_time).do(self._scheduled_quote_check)
                logger.info(f"🔄 Scheduled quote retweet check at {quote_time}")

            # 定期メンテナンス（毎日深夜）
            maintenance_tasks = MAINTENANCE_TASKS_COUNT
            schedule.every().day.at("03:00").do(self._daily_maintenance)

            logger.info(
                f"✅ Schedule setup completed: {len(post_times)} posts, "
                f"{len(quote_check_times)} quote checks, {maintenance_tasks} maintenance"
            )

        except Exception as e:
            logger.error(f"❌ Failed to setup schedule: {e}")
            raise

    def _scheduled_post(
        self,
        categories: List[str],
        random_delay: bool = True,
        max_delay_minutes: int = 15,
    ) -> None:
        """
        スケジュールされた投稿を実行

        Args:
            categories: 投稿カテゴリのリスト
            random_delay: ランダム遅延を適用するか
            max_delay_minutes: 最大遅延時間（分）
        """
        try:
            # ランダム遅延
            if random_delay and max_delay_minutes > 0:
                delay_seconds = random.randint(0, max_delay_minutes * 60)
                if delay_seconds > 0:
                    logger.info(f"⏱️ Random delay: {delay_seconds} seconds")
                    time.sleep(delay_seconds)

            # カテゴリをランダム選択
            selected_category = random.choice(categories) if categories else None

            # コンテンツ生成
            tweet_content = self.content_generator.generate_tweet_content(category=selected_category)

            if not tweet_content:
                logger.warning("⚠️ No tweet content generated, skipping post")
                return

            # ツイート投稿
            tweet_id = self.twitter_client.post_tweet(tweet_content)

            if tweet_id:
                logger.info(f"🎉 Scheduled tweet posted successfully! ID: {tweet_id}")
                logger.info(f"📝 Content: {tweet_content}")
            else:
                logger.error("❌ Failed to post scheduled tweet")

        except Exception as e:
            logger.error(f"❌ Scheduled post failed: {e}")

    def _daily_maintenance(self) -> None:
        """日次メンテナンス処理"""
        try:
            logger.info("🔧 Starting daily maintenance...")

            # 統計情報をログ出力
            stats = self.content_generator.get_content_stats()
            logger.info(f"📊 Content stats: {stats}")

            # Redis接続テスト
            try:
                self.db_manager.redis_client.ping()
                logger.info("✅ Redis connection: OK")
            except Exception as e:
                logger.warning(f"⚠️ Redis connection issue: {e}")

            # Twitter接続テスト
            if self.twitter_client.test_connection():
                logger.info("✅ Twitter API connection: OK")
            else:
                logger.warning("⚠️ Twitter API connection issue")

            logger.info("✅ Daily maintenance completed")

        except Exception as e:
            logger.error(f"❌ Daily maintenance failed: {e}")

    def _scheduled_quote_check(self) -> None:
        """
        スケジュールされたQuote Retweetチェック
        """
        try:
            logger.info("🔄 Starting scheduled quote retweet check...")

            # Quote Retweetチェック実行
            results = self.auto_quote_retweeter.check_and_quote_tweets()

            if results["success"]:
                logger.info("✅ Quote check completed:")
                logger.info(f"   📊 Checked tweets: {results['checked_tweets']}")
                logger.info(f"   🍽️ Food-related found: {results['food_related_found']}")
                logger.info(f"   🔄 Quote tweets posted: {results['quote_posted']}")

                if results.get("skipped_rate_limit", 0) > 0:
                    logger.info("    ⏰ Skipped due to rate limit")

                errors = results.get("errors", [])
                if errors:
                    log_errors(errors, MAX_ERRORS_TO_DISPLAY)
            else:
                logger.error(f"❌ Quote check failed: {results.get('error', 'Unknown error')}")

            # 古い処理済みツイートをクリーンアップ
            self.auto_quote_retweeter.cleanup_old_processed_tweets()

        except Exception as e:
            logger.error(f"❌ Error in scheduled quote check: {e}")

    def start_scheduler(self, blocking: bool = True) -> None:
        """
        スケジューラーを開始

        Args:
            blocking: ブロッキング実行するか（Falseの場合はバックグラウンド実行）
        """
        try:
            if self.is_running:
                logger.warning("⚠️ Scheduler is already running")
                return

            self.is_running = True

            if blocking:
                logger.info("🚀 Starting scheduler (blocking mode)...")
                self._run_scheduler_loop()
            else:
                logger.info("🚀 Starting scheduler (background mode)...")
                self.scheduler_thread = threading.Thread(target=self._run_scheduler_loop, daemon=True)
                self.scheduler_thread.start()

        except Exception as e:
            logger.error(f"❌ Failed to start scheduler: {e}")
            self.is_running = False
            raise

    def _run_scheduler_loop(self) -> None:
        """スケジューラーループを実行"""
        try:
            logger.info("⏰ Scheduler loop started")

            while self.is_running:
                schedule.run_pending()
                time.sleep(60)  # 1分間隔でチェック

        except Exception as e:
            logger.error(f"❌ Scheduler loop error: {e}")
        finally:
            logger.info("⏹️ Scheduler loop stopped")

    def stop_scheduler(self) -> None:
        """スケジューラーを停止"""
        try:
            if not self.is_running:
                logger.warning("⚠️ Scheduler is not running")
                return

            logger.info("⏹️ Stopping scheduler...")
            self.is_running = False

            # スレッドの終了を待つ
            if self.scheduler_thread and self.scheduler_thread.is_alive():
                self.scheduler_thread.join(timeout=5)

            schedule.clear()
            logger.info("✅ Scheduler stopped")

        except Exception as e:
            logger.error(f"❌ Failed to stop scheduler: {e}")

    def post_now(self, category: Optional[str] = None, tone: Optional[str] = None) -> bool:
        """
        即座にツイートを投稿

        Args:
            category: カテゴリ指定
            tone: トーン指定

        Returns:
            投稿成功かどうか
        """
        try:
            logger.info("📤 Posting tweet now...")

            # コンテンツ生成
            tweet_content = self.content_generator.generate_tweet_content(category=category, tone=tone)

            if not tweet_content:
                logger.warning("⚠️ No tweet content generated")
                return False

            # ツイート投稿
            tweet_id = self.twitter_client.post_tweet(tweet_content)

            if tweet_id:
                logger.info(f"🎉 Tweet posted successfully! ID: {tweet_id}")
                logger.info(f"📝 Content: {tweet_content}")
                return True
            else:
                logger.error("❌ Failed to post tweet")
                return False

        except Exception as e:
            logger.error(f"❌ Post now failed: {e}")
            return False

    def post_custom_tweet(self, text: str) -> bool:
        """
        カスタムテキストでツイートを投稿

        Args:
            text: 投稿するテキスト

        Returns:
            投稿成功かどうか
        """
        try:
            logger.info(f"📤 Posting custom tweet: {text}")

            # 文字数チェック（280文字制限）
            if len(text) > 280:
                logger.warning(f"Tweet too long ({len(text)} chars), truncating...")
                text = text[:277] + "..."

            # ツイート投稿
            success = self.twitter_client.post_tweet(text)

            if success:
                logger.info("🎉 Custom tweet posted successfully!")
                logger.info(f"📝 Content: {text}")
                return True
            else:
                logger.error("❌ Failed to post custom tweet")
                return False

        except Exception as e:
            logger.error(f"❌ Custom tweet failed: {e}")
            return False

    def get_schedule_status(self) -> Dict[str, Any]:
        """
        スケジュールの状態を取得

        Returns:
            スケジュール状態情報
        """
        try:
            jobs = schedule.get_jobs()

            status: dict[str, Any] = {
                "is_running": self.is_running,
                "total_jobs": len(jobs),
                "next_run": str(schedule.next_run()) if jobs else None,
                "jobs": [],
            }

            for job in jobs:
                job_info: dict[str, str] = {
                    "function": getattr(job.job_func, "__name__", "unknown"),
                    "next_run": str(job.next_run),
                    "interval": str(job.interval),
                    "unit": str(job.unit),
                }
                status["jobs"].append(job_info)

            return status

        except Exception as e:
            logger.error(f"❌ Failed to get schedule status: {e}")
            return {"error": str(e)}

    def add_one_time_post(self, delay_minutes: int, category: Optional[str] = None) -> None:
        """
        指定時間後に1回だけ投稿するスケジュールを追加

        Args:
            delay_minutes: 遅延時間（分）
            category: カテゴリ指定
        """
        try:
            job_id = None

            def one_time_post() -> None:
                nonlocal job_id  # noqa: F824
                self._scheduled_post([category] if category else ["お肉", "日常"])
                # この実行後にジョブをキャンセル
                if job_id:
                    schedule.cancel_job(job_id)

            job_id = schedule.every(delay_minutes).minutes.do(one_time_post)
            logger.info(f"⏰ One-time post scheduled in {delay_minutes} minutes")

        except Exception as e:
            logger.error(f"❌ Failed to add one-time post: {e}")

    def close(self) -> None:
        """リソースを解放"""
        try:
            # スケジューラー停止
            self.stop_scheduler()

            # 各コンポーネントを閉じる
            if self.content_generator:
                self.content_generator.close()
            if self.db_manager:
                self.db_manager.close()

            logger.info("✅ Scheduler manager closed")

        except Exception as e:
            logger.error(f"❌ Error closing scheduler manager: {e}")

    def __enter__(self) -> "SchedulerManager":
        """コンテキストマネージャー用"""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """コンテキストマネージャー用"""
        self.close()


def test_scheduler(dry_run: bool = True) -> None:
    """スケジューラーのテスト実行"""
    print(f"🐻 {BOT_NAME} Scheduler test starting...")

    try:
        with SchedulerManager(dry_run=dry_run) as scheduler:
            if dry_run:
                print("🎭 Running in DRY RUN mode - no actual posts will be made")
            else:
                print("⚠️ Running in LIVE mode - real posts will be made")

            # 接続テスト（ドライランモードでは実際の接続テストをスキップ）
            if not dry_run:
                if scheduler.twitter_client.test_connection():
                    print("✅ Twitter connection: OK")
            else:
                print("✅ Mock Twitter connection: OK (dry run)")

            # コンテンツ生成テスト
            content = scheduler.content_generator.generate_tweet_content()
            if content:
                print(f"✅ Content generation: OK - {content}")

            # 即座投稿テスト
            if dry_run:
                print("📤 Testing immediate post (dry run)...")
                print("✅ Mock post successful (would have posted in live mode)")
            else:
                print("📤 Testing immediate post (LIVE)...")
                # result = scheduler.post_now()  # 実際の投稿（必要に応じてコメントアウト）

            # スケジュール設定テスト
            test_config = {
                "daily_posts": 2,
                "post_times": ["10:00", "18:00"],
                "categories": ["お肉"],
                "random_delay": False,
            }
            scheduler.setup_schedule(test_config)

            # スケジュール状態確認
            status = scheduler.get_schedule_status()
            print(f"✅ Schedule status: {status}")

            print("🎉 Scheduler test completed successfully!")

    except Exception as e:
        print(f"❌ Scheduler test failed: {e}")


if __name__ == "__main__":
    test_scheduler(dry_run=True)  # デフォルトはドライラン
