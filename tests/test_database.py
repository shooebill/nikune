import sqlite3
from typing import Any, Iterable, List, Optional, Set, cast
from unittest import TestCase

from nikune.database import DatabaseManager


class FakeRedisClient:
    """clear_all_templates()の検証用に scan_iter/delete/flushdb のみを実装した
    最小限のRedis互換テストダブル（実Redis・fakeredisパッケージ不要）"""

    def __init__(self, keys: Iterable[str]):
        self.store: Set[str] = set(keys)
        self.flushdb_called = False

    def scan_iter(self, match: Optional[str] = None) -> List[str]:
        prefix = match[:-1] if match and match.endswith("*") else (match or "")
        return [key for key in list(self.store) if key.startswith(prefix)]

    def delete(self, key: str) -> None:
        self.store.discard(key)

    def flushdb(self) -> None:
        # このテストダブルでflushdbが呼ばれたら回帰（本番Redis全消去バグの再発）
        self.flushdb_called = True
        self.store.clear()


def _make_db_manager_without_connections() -> DatabaseManager:
    """__init__（実SQLite/Redis接続）をバイパスし、SQLiteはin-memory・Redisは
    テストダブルで組み立てる"""
    db = DatabaseManager.__new__(DatabaseManager)
    db.sqlite_conn = sqlite3.connect(":memory:")
    db.sqlite_conn.row_factory = sqlite3.Row
    db._create_tables()
    return db


class ClearAllTemplatesRedisSafetyTests(TestCase):
    """clear_all_templates()がnikune管理キーのみを削除し、flushdb()（Redis
    インスタンス全体の消去）を使わないことを検証する回帰テスト"""

    def test_clear_all_templates_only_deletes_nikune_managed_keys(self) -> None:
        db = _make_db_manager_without_connections()
        db.add_template("お肉", "元気", "テスト用テンプレート")

        unrelated_key = "other-app:session:abc123"
        fake_redis = FakeRedisClient(
            keys={
                "tweet_history:1:20260101_000000",
                "template_usage:1",
                "recent_tweet:1",
                unrelated_key,
            }
        )
        # 実Redisクライアントの代わりにテストダブルを注入（clear_all_templates()が
        # scan_iter/delete/flushdbしか呼ばないことを前提とした最小限の差し替え）
        db.redis_client = cast(Any, fake_redis)

        db.clear_all_templates()

        self.assertFalse(fake_redis.flushdb_called, "flushdb()は呼ばれてはいけない（他データ全消去のリスク）")
        self.assertEqual(
            fake_redis.store,
            {unrelated_key},
            "nikune管理キー（tweet_history/template_usage/recent_tweet）のみが削除されること",
        )
        self.assertEqual(db.get_templates(active_only=False), [])

    def test_clear_all_templates_handles_no_matching_keys_without_flushdb(self) -> None:
        db = _make_db_manager_without_connections()
        fake_redis = FakeRedisClient(keys={"other-app:foo"})
        db.redis_client = cast(Any, fake_redis)

        # 例外を投げずに完了し、対象外キーも残ること
        db.clear_all_templates()

        self.assertFalse(fake_redis.flushdb_called)
        self.assertEqual(fake_redis.store, {"other-app:foo"})
