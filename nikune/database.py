"""
nikune bot database management
SQLite（マスタデータ）とRedis（動的データ）を統合管理
"""

import csv
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis

from config.settings import BOT_NAME

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DatabaseManager:
    """データベース管理クラス（SQLite + Redis）"""

    def __init__(self, sqlite_path: str = "data/templates.db", redis_host: str = "localhost", redis_port: int = 6379):
        """
        データベースマネージャーを初期化

        Args:
            sqlite_path: SQLiteファイルのパス
            redis_host: Redisホスト
            redis_port: Redisポート
        """
        self.sqlite_path = sqlite_path
        self.redis_host = redis_host
        self.redis_port = redis_port

        # データディレクトリを作成
        os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)

        # データベース接続を初期化
        self._init_sqlite()
        self._init_redis()

        logger.info(f"✅ {BOT_NAME} Database manager initialized")

    def _init_sqlite(self) -> None:
        """SQLiteデータベースを初期化"""
        try:
            self.sqlite_conn = sqlite3.connect(self.sqlite_path)
            self.sqlite_conn.row_factory = sqlite3.Row  # 辞書形式でアクセス可能に
            self._create_tables()
            logger.info("✅ SQLite database initialized")
        except Exception as e:
            logger.error(f"❌ SQLite initialization failed: {e}")
            raise

    def _init_redis(self) -> None:
        """Redis接続を初期化"""
        try:
            self.redis_client = redis.Redis(host=self.redis_host, port=self.redis_port, decode_responses=True)
            # 接続テスト
            self.redis_client.ping()
            logger.info("✅ Redis connection established")
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            raise

    def _create_tables(self) -> None:
        """SQLiteテーブルを作成"""
        cursor = self.sqlite_conn.cursor()

        # ツイートテンプレートテーブル
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tweet_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                tone TEXT NOT NULL,
                template TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        """
        )

        self.sqlite_conn.commit()
        logger.info("✅ SQLite tables created")

    # ===== テンプレート管理（SQLite） =====

    def add_template(self, category: str, tone: str, template: str) -> int:
        """
        新しいテンプレートを追加

        Args:
            category: カテゴリ（お肉、日常、季節等）
            tone: トーン（可愛い、元気、癒し等）
            template: テンプレート文

        Returns:
            追加されたテンプレートのID
        """
        cursor = self.sqlite_conn.cursor()
        cursor.execute(
            """
            INSERT INTO tweet_templates (category, tone, template)
            VALUES (?, ?, ?)
        """,
            (category, tone, template),
        )

        template_id: int = cursor.lastrowid or 0
        self.sqlite_conn.commit()

        logger.info(f"✅ Template added: ID={template_id}, Category={category}")
        return template_id

    def get_templates(
        self, category: Optional[str] = None, tone: Optional[str] = None, active_only: bool = True
    ) -> List[Dict[str, str]]:
        """
        テンプレートを取得

        Args:
            category: カテゴリでフィルタ
            tone: トーンでフィルタ
            active_only: アクティブなテンプレートのみ

        Returns:
            テンプレートのリスト
        """
        cursor = self.sqlite_conn.cursor()

        query = "SELECT * FROM tweet_templates WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)

        if tone:
            query += " AND tone = ?"
            params.append(tone)

        if active_only:
            query += " AND is_active = 1"

        cursor.execute(query, params)
        templates = [dict(row) for row in cursor.fetchall()]

        logger.info(f"📋 Retrieved {len(templates)} templates")
        return templates

    def get_random_template(
        self, category: Optional[str] = None, tone: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """
        ランダムなテンプレートを取得

        Args:
            category: カテゴリでフィルタ
            tone: トーンでフィルタ

        Returns:
            ランダムなテンプレート（辞書形式）
        """
        templates = self.get_templates(category, tone, active_only=True)

        if not templates:
            logger.warning("⚠️ No templates found")
            return None

        import random

        template = random.choice(templates)

        logger.info(f"🎲 Random template selected: ID={template['id']}, Category={template['category']}")
        return template

    # ===== 動的データ管理（Redis） =====

    def record_tweet_usage(self, template_id: int, tweet_text: str, ttl_hours: int = 24) -> None:
        """
        ツイート使用履歴を記録

        Args:
            template_id: 使用したテンプレートのID
            tweet_text: 実際のツイート内容
            ttl_hours: 記録保持時間（時間）
        """
        try:
            # 使用履歴を記録
            key = f"tweet_history:{template_id}:{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.redis_client.setex(key, ttl_hours * 3600, tweet_text)

            # 使用頻度カウンターを増加
            usage_key = f"template_usage:{template_id}"
            self.redis_client.incr(usage_key)

            # 重複防止用の短期フラグ
            recent_key = f"recent_tweet:{template_id}"
            self.redis_client.setex(recent_key, 86400, "used")  # 24時間

            logger.info(f"📝 Tweet usage recorded: Template ID={template_id}")

        except Exception as e:
            logger.error(f"❌ Failed to record tweet usage: {e}")

    def can_use_template(self, template_id: int, cooldown_hours: int = 24) -> bool:
        """
        テンプレートが使用可能かチェック（重複防止）

        Args:
            template_id: テンプレートID
            cooldown_hours: クールダウン時間（時間）

        Returns:
            使用可能かどうか
        """
        try:
            recent_key = f"recent_tweet:{template_id}"
            exists = self.redis_client.exists(recent_key)

            can_use = not exists
            logger.info(f"🔍 Template {template_id} usage check: {'Available' if can_use else 'On cooldown'}")
            return can_use

        except Exception as e:
            logger.error(f"❌ Failed to check template availability: {e}")
            return True  # エラー時は使用可能とする

    def get_template_usage_stats(self, template_id: int) -> Dict[str, str]:
        """
        テンプレートの使用統計を取得

        Args:
            template_id: テンプレートID

        Returns:
            使用統計情報
        """
        try:
            usage_key = f"template_usage:{template_id}"
            usage_count_raw = self.redis_client.get(usage_key)
            if usage_count_raw and isinstance(usage_count_raw, (str, bytes)):
                usage_count = int(usage_count_raw.decode() if isinstance(usage_count_raw, bytes) else usage_count_raw)
            else:
                usage_count = 0

            stats = {
                "template_id": str(template_id),
                "usage_count": str(usage_count),
                "last_checked": datetime.now().isoformat(),
            }

            return stats

        except Exception as e:
            logger.error(f"❌ Failed to get usage stats: {e}")
            return {"template_id": str(template_id), "usage_count": "0", "error": str(e)}

    def get_available_template(
        self, category: Optional[str] = None, tone: Optional[str] = None, max_attempts: int = 10
    ) -> Optional[Dict[str, str]]:
        """
        使用可能なテンプレートを取得（重複防止付き）

        Args:
            category: カテゴリでフィルタ
            tone: トーンでフィルタ
            max_attempts: 最大試行回数

        Returns:
            使用可能なテンプレート
        """
        for attempt in range(max_attempts):
            template = self.get_random_template(category, tone)

            if not template:
                break

            if self.can_use_template(int(template["id"])):
                return template

            logger.info(f"🔄 Template {template['id']} on cooldown, trying another...")

        logger.warning("⚠️ No available templates found after max attempts")
        return None

    # ===== スプレッドシート連携 =====

    def import_templates_from_tsv(self, tsv_file_path: str, clear_existing: bool = False) -> int:
        """
        TSVファイルからテンプレートをインポート

        Args:
            tsv_file_path: TSVファイルのパス
            clear_existing: 既存のテンプレートをクリアするか

        Returns:
            インポートされたテンプレート数
        """
        try:
            cursor = self.sqlite_conn.cursor()

            # 既存データをクリア（オプション）
            if clear_existing:
                cursor.execute("DELETE FROM tweet_templates")
                logger.info("🗑️ Existing templates cleared")

            imported_count = 0

            with open(tsv_file_path, "r", encoding="utf-8") as tsvfile:
                reader = csv.DictReader(tsvfile, delimiter="\t")

                for row in reader:
                    # 必要なカラムをチェック
                    required_columns = ["category", "tone", "template"]
                    if not all(col in row for col in required_columns):
                        logger.warning(f"⚠️ Missing required columns in row: {row}")
                        continue

                    # テンプレートを追加
                    cursor.execute(
                        """
                        INSERT INTO tweet_templates (category, tone, template)
                        VALUES (?, ?, ?)
                    """,
                        (row["category"], row["tone"], row["template"]),
                    )

                    imported_count += 1

            self.sqlite_conn.commit()
            logger.info(f"✅ Imported {imported_count} templates from TSV")
            return imported_count

        except Exception as e:
            logger.error(f"❌ Failed to import templates from TSV: {e}")
            return 0

    def clear_all_templates(self) -> None:
        """
        全てのテンプレートを削除（SQLite + Redis）
        """
        try:
            # SQLiteから全テンプレートを削除
            cursor = self.sqlite_conn.cursor()
            cursor.execute("DELETE FROM tweet_templates")
            self.sqlite_conn.commit()
            logger.info("🗑️ All templates cleared from SQLite")

            # Redisから全データを削除
            self.redis_client.flushdb()
            logger.info("🗑️ All data cleared from Redis")

        except Exception as e:
            logger.error(f"❌ Failed to clear templates: {e}")
            raise

    def export_templates_to_tsv(self, tsv_file_path: str, category: Optional[str] = None) -> int:
        """
        テンプレートをTSVファイルにエクスポート

        Args:
            tsv_file_path: エクスポート先TSVファイルのパス
            category: カテゴリでフィルタ（Noneの場合は全件）

        Returns:
            エクスポートされたテンプレート数
        """
        try:
            # テンプレートを取得
            templates = self.get_templates(category=category, active_only=False)

            if not templates:
                logger.warning("⚠️ No templates to export")
                return 0

            # TSVファイルに書き込み
            with open(tsv_file_path, "w", newline="", encoding="utf-8") as tsvfile:
                fieldnames = ["id", "category", "tone", "template", "created_at", "is_active"]
                writer = csv.DictWriter(tsvfile, fieldnames=fieldnames, delimiter="\t")

                writer.writeheader()
                for template in templates:
                    writer.writerow(template)

            logger.info(f"✅ Exported {len(templates)} templates to TSV")
            return len(templates)

        except Exception as e:
            logger.error(f"❌ Failed to export templates to TSV: {e}")
            return 0

    # ===== ユーティリティ =====

    def close(self) -> None:
        """データベース接続を閉じる"""
        try:
            if hasattr(self, "sqlite_conn"):
                self.sqlite_conn.close()
            if hasattr(self, "redis_client"):
                self.redis_client.close()  # type: ignore
            logger.info("✅ Database connections closed")
        except Exception as e:
            logger.error(f"❌ Error closing database connections: {e}")

    def __enter__(self) -> "DatabaseManager":
        """コンテキストマネージャー用"""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """コンテキストマネージャー用"""
        self.close()


# テスト用関数
def test_database_manager() -> None:
    """データベースマネージャーのテスト実行"""
    print(f"🐻 {BOT_NAME} Database manager test starting...")

    try:
        with DatabaseManager() as db:
            # サンプルTSVを作成
            tsv_path = "data/sample_templates.tsv"
            print(f"✅ Sample TSV path: {tsv_path}")

            # TSVからインポート
            imported_count = db.import_templates_from_tsv(tsv_path, clear_existing=True)
            print(f"✅ Imported {imported_count} templates from TSV")

            # テンプレートを取得
            templates = db.get_templates()
            print(f"✅ Retrieved {len(templates)} templates")

            # ランダムテンプレートを取得
            random_template = db.get_random_template()
            if random_template:
                print(f"✅ Random template: {random_template['template']}")

                # 使用履歴を記録
                db.record_tweet_usage(int(random_template["id"]), "テストツイート", ttl_hours=1)
                print("✅ Tweet usage recorded")

                # 使用可能性をチェック
                can_use = db.can_use_template(int(random_template["id"]))
                print(f"✅ Template availability: {'Available' if can_use else 'On cooldown'}")

            # TSVエクスポートテスト
            export_path = "data/exported_templates.tsv"
            exported_count = db.export_templates_to_tsv(export_path)
            print(f"✅ Exported {exported_count} templates to TSV")

            print("🎉 Database manager test completed successfully!")

    except Exception as e:
        print(f"❌ Database manager test failed: {e}")


if __name__ == "__main__":
    test_database_manager()
