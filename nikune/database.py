"""
nikune bot database management
SQLite（マスタデータ）とRedis（動的データ）を統合管理
"""

import csv
import logging
import os
import random
import sqlite3
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import redis

from config.settings import BOT_NAME, TIME_LIMITED_TONES

# 独り言ツイートのセリフ選び（get_available_template）
# 直近に使ったセリフのうち、候補全体のこの割合にあたる本数を避ける
# （19本・1日3回なら直近11本を避けるので、同じセリフは早くても4日後）
RECENT_AVOID_RATIO = 0.6
# 直近この回数の投稿と「ほぼ同じ文」のセリフも避ける
SIMILAR_LOOKBACK = 3
# 「ほぼ同じ文」とみなす一致度（difflib）。一語だけ入れ替えた長いセリフや、語尾だけ違うセリフが当たる。
# 「肉ね！」「うお肉ね！」のような短い連作（0.75）は当たらない値にしている
SIMILARITY_THRESHOLD = 0.85
# 時間帯の制限がないトーンのセリフを出してよい「時」（＝いつでも）
ALL_HOURS = frozenset(range(24))


def _is_later_step(template: Dict[str, Any]) -> bool:
    """続きもの（series）の2番目以降のセリフかどうか"""
    return bool(template.get("series")) and int(template.get("series_order") or 1) > 1


# ログ設定
# ロギングの基本設定（ハンドラ・フォーマット）はエントリポイント（main.py）側で行う。
# ライブラリ側のモジュールでlogging.basicConfig()を呼ぶと、最初に呼ばれた設定だけが
# 有効になるPythonの仕様上、import順序次第でmain.py側のフォーマット設定が
# 無効化されてしまうため、ここではLoggerの取得のみを行う。
logger = logging.getLogger(__name__)


class DatabaseManager:
    """データベース管理クラス（SQLite + Redis）"""

    # nikuneが管理するRedisキーのプレフィックス一覧
    # （record_tweet_usage/can_use_template/get_template_usage_statsで使用しているキーと一致させること）
    REDIS_KEY_PREFIXES = ("tweet_history:", "template_usage:", "recent_tweet:")

    def __init__(
        self,
        sqlite_path: str = "data/templates.db",
        redis_host: str = "localhost",
        redis_port: int = 6379,
    ):
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
        self._closed = False  # クローズ状態フラグ

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
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                decode_responses=True,
                socket_connect_timeout=5,  # 接続タイムアウト（秒）
                socket_timeout=5,  # ソケットタイムアウト（秒）
                retry_on_timeout=True,  # タイムアウト時のリトライ
            )
            # 接続テスト
            self.redis_client.ping()
            logger.info("✅ Redis connection established")
        except redis.ConnectionError as e:
            logger.error(f"❌ Redis connection failed: {e}")
            logger.error("💡 Redisサーバーが起動しているか確認してください")
            raise
        except redis.TimeoutError as e:
            logger.error(f"❌ Redis connection timeout: {e}")
            logger.error("💡 Redisサーバーの応答が遅い可能性があります")
            raise
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

        # 続きもののセリフ（前振り→オチ）の列。以前に作ったDBにはないので、なければ足す
        existing_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(tweet_templates)")}
        if "series" not in existing_columns:
            cursor.execute("ALTER TABLE tweet_templates ADD COLUMN series TEXT")
        if "series_order" not in existing_columns:
            cursor.execute("ALTER TABLE tweet_templates ADD COLUMN series_order INTEGER")

        # 引用RTの履歴テーブル（cronで毎回別プロセスとして起動しても、同じツイートを再度引用しないため・
        # 実行をまたいでレート制限を効かせるために使う。--setup-db でも消さない）
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS quote_history (
                source_tweet_id TEXT PRIMARY KEY,
                quote_tweet_id TEXT NOT NULL,
                priority_score INTEGER NOT NULL,
                quoted_at TEXT NOT NULL
            )
        """
        )

        # 独り言ツイートの履歴テーブル（最近使ったセリフを避けて選ぶために使う。--setup-db でも消さない。
        # テンプレートを入れ直すとIDが変わるので、セリフの本文も持っておく）
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS post_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL,
                template_text TEXT NOT NULL,
                posted_at TEXT NOT NULL
            )
        """
        )

        self.sqlite_conn.commit()
        logger.info("✅ SQLite tables created")

    # ===== テンプレート管理（SQLite） =====

    def add_template(
        self,
        category: str,
        tone: str,
        template: str,
        series: Optional[str] = None,
        series_order: Optional[int] = None,
    ) -> int:
        """
        新しいテンプレートを追加

        Args:
            category: カテゴリ（お肉、日常、季節等）
            tone: トーン（可愛い、元気、癒し等）
            template: テンプレート文
            series: 続きもののネタ名（前振り→オチの組に同じ名前を付ける）。単発のセリフはNone
            series_order: 続きものの中での順番（1が前振り、2がその次）

        Returns:
            追加されたテンプレートのID
        """
        cursor = self.sqlite_conn.cursor()
        cursor.execute(
            """
            INSERT INTO tweet_templates (category, tone, template, series, series_order)
            VALUES (?, ?, ?, ?, ?)
        """,
            (category, tone, template, series, series_order),
        )

        template_id: int = cursor.lastrowid or 0
        self.sqlite_conn.commit()

        logger.info(f"✅ Template added: ID={template_id}, Category={category}")
        return template_id

    def get_templates(
        self,
        category: Optional[str] = None,
        tone: Optional[str] = None,
        active_only: bool = True,
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

        template = random.choice(templates)

        logger.info(f"🎲 Random template selected: ID={template['id']}, Category={template['category']}")
        return template

    # ===== 引用RT履歴（SQLite） =====

    def record_quote(self, source_tweet_id: str, quote_tweet_id: str, priority_score: int, quoted_at: datetime) -> None:
        """
        引用RTした記録を保存する

        Args:
            source_tweet_id: 引用元ツイートのID
            quote_tweet_id: 投稿した引用RTのID
            priority_score: 引用元ツイートの優先度スコア
            quoted_at: 投稿時刻（ローカル時刻）
        """
        cursor = self.sqlite_conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO quote_history (source_tweet_id, quote_tweet_id, priority_score, quoted_at)
            VALUES (?, ?, ?, ?)
        """,
            (str(source_tweet_id), str(quote_tweet_id), priority_score, quoted_at.isoformat()),
        )
        self.sqlite_conn.commit()

    def has_quoted(self, source_tweet_id: str) -> bool:
        """引用元ツイートを過去に引用RTしたことがあるか"""
        cursor = self.sqlite_conn.cursor()
        cursor.execute("SELECT 1 FROM quote_history WHERE source_tweet_id = ?", (str(source_tweet_id),))
        return cursor.fetchone() is not None

    def get_quotes_since(self, since: datetime) -> List[Dict[str, Any]]:
        """
        指定時刻以降の引用RTを古い順に取得する

        Returns:
            {"quoted_at": datetime, "priority_score": int} のリスト
        """
        cursor = self.sqlite_conn.cursor()
        cursor.execute(
            "SELECT quoted_at, priority_score FROM quote_history WHERE quoted_at > ? ORDER BY quoted_at",
            (since.isoformat(),),
        )
        return [
            {"quoted_at": datetime.fromisoformat(row["quoted_at"]), "priority_score": int(row["priority_score"])}
            for row in cursor.fetchall()
        ]

    # ===== 独り言ツイートの履歴（SQLite） =====

    def record_post(self, template_id: int, posted_at: Optional[datetime] = None) -> None:
        """投稿したテンプレートを履歴に記録する（テンプレートが見つからなければ何もしない）"""
        cursor = self.sqlite_conn.cursor()
        cursor.execute("SELECT template FROM tweet_templates WHERE id = ?", (template_id,))
        row = cursor.fetchone()
        if row is None:
            logger.warning(f"⚠️ Template {template_id} not found, post history not recorded")
            return
        cursor.execute(
            "INSERT INTO post_history (template_id, template_text, posted_at) VALUES (?, ?, ?)",
            (template_id, row["template"], (posted_at or datetime.now()).isoformat()),
        )
        self.sqlite_conn.commit()

    def get_recent_post_texts(self, limit: int) -> List[str]:
        """最近投稿したセリフ（テンプレートの本文）を新しい順に返す"""
        cursor = self.sqlite_conn.cursor()
        cursor.execute("SELECT template_text FROM post_history ORDER BY id DESC LIMIT ?", (limit,))
        return [str(row["template_text"]) for row in cursor.fetchall()]

    # ===== 動的データ管理（Redis） =====

    def record_tweet_usage(self, template_id: int, tweet_text: str, ttl_hours: int = 24) -> None:
        """
        ツイート使用履歴を記録

        Args:
            template_id: 使用したテンプレートのID
            tweet_text: 実際のツイート内容
            ttl_hours: 記録保持時間（時間）
        """
        # 最近使ったセリフを避けるための履歴（SQLite）。Redisの記録に失敗しても残るよう先に書く
        try:
            self.record_post(template_id)
        except Exception as e:
            logger.error(f"❌ Failed to record post history: {e}")

        try:
            # 使用履歴を記録
            key = f"tweet_history:{template_id}:{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.redis_client.setex(key, ttl_hours * 3600, tweet_text)

            # 使用頻度カウンターを増加
            usage_key = f"template_usage:{template_id}"
            self.redis_client.incr(usage_key)

            # 重複防止用の短期フラグ（クールダウン判定に使うTTLはttl_hours引数に従う。
            # 以前は86400秒（24時間）に決め打ちされており、can_use_template()が実際に
            # 参照するこのキーにttl_hoursが反映されていなかった）
            recent_key = f"recent_tweet:{template_id}"
            self.redis_client.setex(recent_key, ttl_hours * 3600, "used")

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
            return {
                "template_id": str(template_id),
                "usage_count": "0",
                "error": str(e),
            }

    def get_available_template(
        self,
        category: Optional[str] = None,
        tone: Optional[str] = None,
        max_attempts: int = 10,
        now: Optional[datetime] = None,
    ) -> Optional[Dict[str, str]]:
        """
        使用可能なテンプレートを取得（最近使ったセリフ・それに似たセリフを避ける）

        以前は「全体からランダムに選び、24時間以内に使ったものだけ引き直す」方式で、
        同じセリフが28時間後に戻ってきたり、ほぼ同じ文が続けて出たりしていた。
        今は次の順に候補を絞り、残った中からランダムに選ぶ:

            0. 今の時間帯に出せないセリフ（TIME_LIMITED_TONES のトーンで、時間帯が外れているもの）を外す
               続きもの（series）の2番目以降も外す。直前の投稿が同じ続きものの1つ前だったときだけ、
               ここで外す前に「続き」として優先して選ぶ（前振りの次の回にオチが出る）
            1. 直近に使ったセリフ（候補全体の RECENT_AVOID_RATIO にあたる本数）を外す
            2. 直近 SIMILAR_LOOKBACK 回の投稿とほぼ同じ文（一部だけ違うセリフ）を外す

        候補がなくなったら 2 → 1 の順に条件をゆるめる（0 はゆるめない）。24時間のクールダウン
        （Redis）は従来どおり最後に確認する。

        Args:
            category: カテゴリでフィルタ
            tone: トーンでフィルタ。明示したときは時間帯の制限をかけない（手動で試せるように）
            max_attempts: クールダウン中だったときに選び直す最大回数
            now: 時間帯の判定に使う時刻（省略時は現在時刻）

        Returns:
            使用可能なテンプレート
        """
        templates = self.get_templates(category, tone, active_only=True)
        if tone is None:
            hour = (now or datetime.now()).hour
            templates = [t for t in templates if hour in TIME_LIMITED_TONES.get(t["tone"], ALL_HOURS)]
        if not templates:
            logger.warning("⚠️ No templates found")
            return None

        follow_up = self._follow_up_of_last_post(templates)
        if follow_up is not None:
            logger.info(f"🎬 Follow-up template selected: ID={follow_up['id']}, Series={follow_up['series']}")
            if self.can_use_template(int(follow_up["id"])):
                return follow_up

        # 続きものの2番目以降は、前振りの直後にしか出さない
        templates = [t for t in templates if not _is_later_step(t)]
        if not templates:
            logger.warning("⚠️ No templates found")
            return None

        candidates = self._templates_avoiding_recent(templates)
        random.shuffle(candidates)

        for template in candidates[:max_attempts]:
            logger.info(f"🎲 Random template selected: ID={template['id']}, Category={template['category']}")
            if self.can_use_template(int(template["id"])):
                return template

            logger.info(f"🔄 Template {template['id']} on cooldown, trying another...")

        logger.warning("⚠️ No available templates found after max attempts")
        return None

    def _follow_up_of_last_post(self, templates: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """直前の投稿が続きものだったとき、その次の順番のセリフを返す（なければNone）"""
        last_posts = self.get_recent_post_texts(limit=1)
        if not last_posts:
            return None

        cursor = self.sqlite_conn.cursor()
        cursor.execute(
            "SELECT series, series_order FROM tweet_templates"
            " WHERE template = ? AND series IS NOT NULL AND series_order IS NOT NULL",
            (last_posts[0],),
        )
        last = cursor.fetchone()
        if last is None:
            return None

        next_steps = [
            t for t in templates if t["series"] == last["series"] and t["series_order"] == last["series_order"] + 1
        ]
        return random.choice(next_steps) if next_steps else None

    def _templates_avoiding_recent(self, templates: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """最近使ったセリフと、直近の投稿に似たセリフを外した候補を返す（空になるなら条件をゆるめる）"""
        # 同じセリフが何度か出ていても avoid_count 種類ぶん遡れるよう、多めに読む
        recent = self.get_recent_post_texts(limit=len(templates) * 3)
        avoid_count = int(len(templates) * RECENT_AVOID_RATIO)
        recently_used = set(list(dict.fromkeys(recent))[:avoid_count])
        last_posts = recent[:SIMILAR_LOOKBACK]

        def too_similar(text: str) -> bool:
            return any(SequenceMatcher(None, text, last).ratio() >= SIMILARITY_THRESHOLD for last in last_posts)

        not_recent = [t for t in templates if t["template"] not in recently_used]
        not_similar = [t for t in not_recent if not too_similar(t["template"])]

        skipped = len(templates) - len(not_similar)
        if not_similar:
            logger.info(f"🧹 Avoiding {skipped} recently used or similar templates ({len(not_similar)} left)")
            return not_similar
        if not_recent:
            return not_recent
        return list(templates)

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
                    # 続きもの（series/order列）は任意。列がない・空欄のTSVは単発のセリフとして扱う
                    series = (row.get("series") or "").strip() or None
                    order_text = (row.get("order") or "").strip()
                    series_order = int(order_text) if series and order_text.isdigit() else None
                    if series and series_order is None:
                        logger.warning(f"⚠️ series '{series}' has no valid order, imported as a standalone line")
                        series = None

                    cursor.execute(
                        """
                        INSERT INTO tweet_templates (category, tone, template, series, series_order)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (row["category"], row["tone"], row["template"], series, series_order),
                    )

                    imported_count += 1

            self.sqlite_conn.commit()
            logger.info(f"✅ Imported {imported_count} templates from TSV")
            return imported_count

        except Exception as e:
            logger.error(f"❌ Failed to import templates from TSV: {e}")
            return 0

    def _delete_keys_by_prefix(self, prefix: str) -> int:
        """
        指定したプレフィックスに一致するRedisキーのみをSCAN+DELETEで削除

        Redisインスタンス全体をflushdbすると、同じRedis/DBインデックスを
        共有する他のデータ（他プロセス・他用途のキー）まで消えてしまうため、
        nikuneが実際に使用しているキーだけを対象にする。

        Args:
            prefix: 削除対象のキープレフィックス

        Returns:
            削除したキー数
        """
        deleted = 0
        for key in self.redis_client.scan_iter(match=f"{prefix}*"):
            self.redis_client.delete(key)
            deleted += 1
        return deleted

    def clear_all_templates(self) -> None:
        """
        全てのテンプレートを削除（SQLite + Redis）

        Redis側は`REDIS_KEY_PREFIXES`に列挙したnikune管理キーのみを削除し、
        `flushdb()`のようなRedisインスタンス全体への破壊的操作は行わない。
        """
        try:
            # SQLiteから全テンプレートを削除
            cursor = self.sqlite_conn.cursor()
            cursor.execute("DELETE FROM tweet_templates")
            self.sqlite_conn.commit()
            logger.info("🗑️ All templates cleared from SQLite")

            # Redisからnikune管理キーのみを削除（flushdbは使用しない）
            deleted_keys = 0
            for prefix in self.REDIS_KEY_PREFIXES:
                deleted_keys += self._delete_keys_by_prefix(prefix)
            logger.info(
                f"🗑️ Cleared {deleted_keys} nikune-managed Redis keys "
                f"(prefixes: {', '.join(self.REDIS_KEY_PREFIXES)})"
            )

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
                fieldnames = [
                    "id",
                    "category",
                    "tone",
                    "template",
                    "created_at",
                    "is_active",
                ]
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
            if hasattr(self, "_closed") and self._closed:
                return  # 既にクローズ済み

            if hasattr(self, "sqlite_conn") and self.sqlite_conn:
                self.sqlite_conn.close()
            if hasattr(self, "redis_client") and self.redis_client:
                self.redis_client.close()  # type: ignore[no-untyped-call]

            self._closed = True
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
