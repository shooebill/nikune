"""
nikune bot health check module
システムの健全性をチェックする機能
"""

import logging
import time
from typing import Dict

from config.settings import BOT_NAME
from nikune.database import DatabaseManager
from nikune.twitter_client import TwitterClient

# ログ設定
logger = logging.getLogger(__name__)


class HealthChecker:
    """システム健全性チェッカー"""

    def __init__(self) -> None:
        """ヘルスチェッカーを初期化"""
        self.bot_name = BOT_NAME
        logger.info(f"✅ {self.bot_name} Health checker initialized")

    def check_all_components(self) -> Dict[str, bool]:
        """
        全コンポーネントの健全性をチェック

        Returns:
            各コンポーネントの健全性ステータス
        """
        results = {
            "database": self._check_database(),
            "redis": self._check_redis(),
            "twitter_api": self._check_twitter_api(),
            "overall": True,
        }

        # 全体の健全性を判定
        results["overall"] = all(results.values())

        return results

    def _check_database(self) -> bool:
        """SQLiteデータベースの健全性をチェック"""
        try:
            with DatabaseManager() as db:
                # テンプレート数をチェック
                templates = db.get_templates()
                if len(templates) == 0:
                    logger.warning("⚠️ No templates found in database")
                    return False

                logger.info(f"✅ Database: {len(templates)} templates available")
                return True

        except Exception as e:
            logger.error(f"❌ Database check failed: {e}")
            return False

    def _check_redis(self) -> bool:
        """Redis接続の健全性をチェック"""
        try:
            with DatabaseManager() as db:
                # Redis接続テスト
                db.redis_client.ping()
                logger.info("✅ Redis: Connection successful")
                return True

        except Exception as e:
            logger.error(f"❌ Redis check failed: {e}")
            return False

    def _check_twitter_api(self) -> bool:
        """Twitter API接続の健全性をチェック"""
        try:
            client = TwitterClient()
            if client.test_connection():
                logger.info("✅ Twitter API: Connection successful")
                return True
            else:
                logger.error("❌ Twitter API: Connection failed")
                return False

        except Exception as e:
            logger.error(f"❌ Twitter API check failed: {e}")
            return False

    def get_system_status(self) -> Dict[str, str]:
        """
        システム全体のステータスを取得

        Returns:
            システムステータス情報
        """
        try:
            health_results = self.check_all_components()

            status = {
                "bot_name": self.bot_name,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "overall_health": "✅ Healthy" if health_results["overall"] else "❌ Unhealthy",
                "database_status": "✅ OK" if health_results["database"] else "❌ Failed",
                "redis_status": "✅ OK" if health_results["redis"] else "❌ Failed",
                "twitter_api_status": "✅ OK" if health_results["twitter_api"] else "❌ Failed",
            }

            return status

        except Exception as e:
            logger.error(f"❌ Failed to get system status: {e}")
            return {
                "bot_name": self.bot_name,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "overall_health": "❌ Error",
                "error": str(e),
            }

    def run_diagnostic(self) -> None:
        """詳細な診断を実行"""
        print(f"🐻 {self.bot_name} - System Diagnostic")
        print("=" * 50)

        # ヘルスチェック実行
        health_results = self.check_all_components()

        print(f"📊 Overall Health: {'✅ Healthy' if health_results['overall'] else '❌ Unhealthy'}")
        print(f"🗄️ Database: {'✅ OK' if health_results['database'] else '❌ Failed'}")
        print(f"🔴 Redis: {'✅ OK' if health_results['redis'] else '❌ Failed'}")
        print(f"🐦 Twitter API: {'✅ OK' if health_results['twitter_api'] else '❌ Failed'}")

        # 詳細情報
        if health_results["database"]:
            try:
                with DatabaseManager() as db:
                    templates = db.get_templates()
                    print(f"📝 Templates: {len(templates)} available")

                    # カテゴリ別統計
                    categories: Dict[str, int] = {}
                    for template in templates:
                        cat = template["category"]
                        categories[cat] = categories.get(cat, 0) + 1

                    print("📊 Categories:")
                    for category, count in categories.items():
                        print(f"   - {category}: {count} templates")

            except Exception as e:
                print(f"❌ Failed to get template details: {e}")

        print("\n🎉 Diagnostic completed!")


# テスト用関数
def test_health_checker() -> None:
    """ヘルスチェッカーのテスト実行"""
    print(f"🐻 {BOT_NAME} Health checker test starting...")

    try:
        checker = HealthChecker()
        checker.run_diagnostic()
        print("🎉 Health checker test completed successfully!")

    except Exception as e:
        print(f"❌ Health checker test failed: {e}")


if __name__ == "__main__":
    test_health_checker()
