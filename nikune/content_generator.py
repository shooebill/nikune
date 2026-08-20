"""
nikune bot content generator
お肉コメント生成機能（SQLite + Redis連携）
"""

import csv
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import BOT_NAME, NG_KEYWORDS, TIME_SETTINGS

from .database import DatabaseManager
from .twitter_client import _safe_text_length

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ContentGenerator:
    """コンテンツ生成クラス"""

    # お肉関連キーワード（優先度別分類）
    # 優先度: HIGH(3) > MEDIUM(2) > LOW(1)
    MEAT_KEYWORDS_PRIORITY: Dict[str, Dict[str, Any]] = {
        "HIGH": {
            "keywords": ["ステーキ", "焼肉", "すき焼き", "しゃぶしゃぶ", "ジンギスカン"],
            "priority": 3,
            "description": "高品質・特別なお肉料理",
        },
        "MEDIUM": {
            "keywords": [
                "肉",
                "お肉",
                "牛肉",
                "豚肉",
                "鶏肉",
                "ラム肉",
                "ハンバーグ",
                "バーベキュー",
                "BBQ",
                "ローストビーフ",
            ],
            "priority": 2,
            "description": "一般的なお肉料理・食材",
        },
        "LOW": {
            "keywords": [
                "焼き鳥",
                "唐揚げ",
                "とんかつ",
                "牛丼",
                "豚丼",
                "焼き豚",
                "ミートボール",
                "ハンバーガー",
                "チキン",
                "ポーク",
                "ビーフ",
                "肉汁",
            ],
            "priority": 1,
            "description": "日常的なお肉料理・カジュアル",
        },
    }

    # 食・レストラン関連キーワード（優先度別分類、お肉以外）
    # MEAT_KEYWORDS_PRIORITYと同じ優先度体系（HIGH=3, MEDIUM=2, LOW=1）で、
    # 対象カテゴリを食・レストラン全般に拡張する。誤検出を避けるため、
    # 「ご飯」「美味しい」等の汎用語は含めず、具体的な料理名・シーン名詞のみ採用。
    FOOD_KEYWORDS_PRIORITY: Dict[str, Dict[str, Any]] = {
        "HIGH": {
            "keywords": ["寿司", "フレンチ", "懐石", "鉄板焼き"],
            "priority": 3,
            "description": "特別・高品質な食体験",
        },
        "MEDIUM": {
            "keywords": ["カレー", "ラーメン", "パスタ", "うどん", "そば", "餃子", "中華", "レストラン", "グルメ"],
            "priority": 2,
            "description": "一般的な料理・外食シーン",
        },
        "LOW": {
            "keywords": ["お弁当", "ランチ", "居酒屋", "ファミレス", "コンビニごはん"],
            "priority": 1,
            "description": "日常的な食シーン",
        },
    }

    # 後方互換性のため、従来のMEAT_KEYWORDSも維持
    @property
    def MEAT_KEYWORDS(self) -> list[str]:
        """MEAT_KEYWORDS_PRIORITYから動的に生成されるお肉キーワードリスト"""
        return [kw for v in self.MEAT_KEYWORDS_PRIORITY.values() for kw in v["keywords"]]

    # NGワード（設定ファイルから読み込み）
    NG_KEYWORDS = NG_KEYWORDS

    # --- 引用コメント文言について ---
    # 実際の文言は非公開スプレッドシート（tweet_templateのpersonaタブ等）で起草・管理し、
    # data/quote_comments.tsv（gitignore対象）としてエクスポートしたものを実行時に読み込む。
    # ここに書かれているのはファイル未配置時の最小限フォールバックのみで、公開済みの
    # docs/CHARACTER_PERSONA_SAMPLE.md 記載の口癖（肉ね！等）の範囲に留めている。
    # 詳細は _load_quote_comments() を参照。
    _FALLBACK_SPECIFIC_KEYWORD_COMMENTS: List[tuple[str, List[str]]] = [
        ("ステーキ", ["肉ね！"]),
        ("焼肉", ["肉だ！"]),
    ]
    _FALLBACK_HIGH_PRIORITY_COMMENTS: List[str] = ["肉ね！", "肉よ！"]
    _FALLBACK_MEDIUM_PRIORITY_COMMENTS: List[str] = ["肉ね！美味しそう！", "肉だ！"]
    _FALLBACK_DEFAULT_QUOTE_COMMENTS: List[str] = ["肉ね！", "肉よ！", "肉しか見えない"]

    # 時間帯判定用設定（config/settings.pyから読み込み）
    MORNING_START = TIME_SETTINGS["MORNING_START"]
    MORNING_END = TIME_SETTINGS["MORNING_END"]
    LUNCH_START = TIME_SETTINGS["LUNCH_START"]
    LUNCH_END = TIME_SETTINGS["LUNCH_END"]
    DINNER_START = TIME_SETTINGS["DINNER_START"]
    DINNER_END = TIME_SETTINGS["DINNER_END"]

    # 正規表現パターン定数（可読性向上のため分割定義）
    # 日本語文字クラス: ひらがな、カタカナ、漢字（拡張Aも含む）
    # \u3400-\u4DBF（CJK統合漢字拡張A）は、稀に使われる漢字や人名・地名などの対応、将来的な拡張性を考慮して含めています。
    JAPANESE_CHARS = r"\u3040-\u309F\u30A0-\u30FF\u3400-\u4DBF\u4E00-\u9FFF"
    # 単語境界パターン: 英数字または日本語文字以外
    WORD_BOUNDARY_PATTERN = rf"[^\w{JAPANESE_CHARS}]"

    # 引用コメント文言のエクスポート先（非公開スプレッドシート由来、gitignore対象）
    QUOTE_COMMENTS_FILE = "data/quote_comments.tsv"

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        コンテンツジェネレーターを初期化

        Args:
            db_manager: データベースマネージャー（Noneの場合は新規作成）
        """
        self.db_manager = db_manager or DatabaseManager()
        self.bot_name = BOT_NAME

        # NGワード正規表現パターンを初期化時にコンパイル（パフォーマンス最適化）
        try:
            self._ng_pattern: Optional[re.Pattern[str]] = self._compile_ng_pattern()
        except re.error as e:
            logger.error(f"❌ Failed to compile NG pattern (regex error): {e}")
            # フォールバック: Noneを使用（NGワード機能を無効化）
            self._ng_pattern = None
            logger.warning("⚠️ NG word filtering disabled due to pattern compilation failure")
        except ValueError as e:
            logger.error(f"❌ Failed to compile NG pattern (value error): {e}")
            # フォールバック: Noneを使用（NGワード機能を無効化）
            self._ng_pattern = None
            logger.warning("⚠️ NG word filtering disabled due to pattern compilation failure")

        # お肉キーワードは絵文字ルール（肉トピック判定）用に集合化しておく
        self._meat_keyword_set = frozenset(self.MEAT_KEYWORDS)

        # お肉＋食・レストランキーワードをレベル別にマージ（優先度別分類）
        self._combined_keywords_priority: Dict[str, Dict[str, Any]] = self._merge_keyword_priorities(
            self.MEAT_KEYWORDS_PRIORITY, self.FOOD_KEYWORDS_PRIORITY
        )

        # 食キーワード（お肉+食・レストラン）の正規表現パターンを事前コンパイル（パフォーマンス最適化v2）
        try:
            self._food_patterns: Dict[str, re.Pattern[str]] = self._compile_food_patterns()
            logger.info("✅ Food keyword patterns pre-compiled for better performance")
        except Exception as e:
            logger.error(f"❌ Failed to compile food patterns: {e}")
            self._food_patterns = {}
            logger.warning("⚠️ Using fallback string matching for food keywords")

        # 引用コメント文言を読み込み（非公開スプレッドシート由来のファイル、未配置時はフォールバック）
        (
            self._specific_keyword_comments,
            self._high_priority_comments,
            self._medium_priority_comments,
            self._default_quote_comments,
        ) = self._load_quote_comments()

        logger.info(f"✅ {self.bot_name} Content generator initialized")

    @property
    def high_priority_score(self) -> int:
        """
        食（お肉＋食・レストラン統合）のHIGH優先度スコア

        呼び出し元（auto_quote_retweeter.py）が高優先度レート制限の閾値として参照する。
        MEAT_KEYWORDS_PRIORITYのみでなく、統合後の_combined_keywords_priorityを参照する
        ことで、お肉と食・レストランのHIGH優先度が将来的に異なる値になっても整合を保つ。
        """
        return int(self._combined_keywords_priority["HIGH"]["priority"])

    def _compile_ng_pattern(self) -> Optional[re.Pattern[str]]:
        """
        NGワードの正規表現パターンを1つにまとめてコンパイル

        Returns:
            コンパイル済みの正規表現パターン（NGワード未設定時はNone）

        Raises:
            re.error: 正規表現のコンパイルに失敗した場合
            ValueError: NGキーワードが無効な場合
        """
        if not self.NG_KEYWORDS:
            # NGワードが未設定の場合はフィルタリングを無効化（Noneを返す）
            logger.info("NGキーワードが未設定のため、NGワードフィルタリングをスキップします")
            return None

        # NGワード本体をエスケープして'|'で連結（空文字列を除外）
        words = [re.escape(ng_word) for ng_word in self.NG_KEYWORDS if ng_word]
        if not words:
            return None

        # 前方・後方境界を含めたパターンを組み立て
        prefix = rf"(?:^|{self.WORD_BOUNDARY_PATTERN})"
        suffix = rf"(?:{self.WORD_BOUNDARY_PATTERN}|$)"
        pattern = f"{prefix}(?:{'|'.join(words)}){suffix}"

        compiled = re.compile(pattern)
        logger.debug(f"📋 Compiled unified NG word pattern with {len(self.NG_KEYWORDS)} keywords")
        return compiled

    @staticmethod
    def _merge_keyword_priorities(
        *priority_dicts: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """
        複数の優先度別キーワード辞書（MEAT_KEYWORDS_PRIORITY形式）をレベル単位でマージ

        同じレベル（HIGH/MEDIUM/LOW）のキーワードリストを結合・重複除去する。
        priorityは各辞書で共通の値を前提とし、最初に見つかった値を採用する。

        Args:
            *priority_dicts: マージ対象の優先度別キーワード辞書（複数可）

        Returns:
            マージ後の優先度別キーワード辞書
        """
        merged: Dict[str, Dict[str, Any]] = {}

        for priority_dict in priority_dicts:
            for level, data in priority_dict.items():
                if level not in merged:
                    merged[level] = {
                        "keywords": [],
                        "priority": data["priority"],
                        "description": data["description"],
                    }

                existing_keywords: list[str] = merged[level]["keywords"]
                for keyword in data["keywords"]:
                    if keyword not in existing_keywords:
                        existing_keywords.append(keyword)

        return merged

    def _compile_food_patterns(self) -> Dict[str, re.Pattern[str]]:
        """
        食キーワード（お肉＋食・レストラン）の正規表現パターンを優先度別に事前コンパイル

        Returns:
            優先度レベル別のコンパイル済み正規表現パターン辞書

        Raises:
            re.error: 正規表現のコンパイルに失敗した場合
        """
        compiled_patterns = {}

        for level, priority_data in self._combined_keywords_priority.items():
            keywords: list[str] = priority_data["keywords"]
            if not keywords:
                continue

            # キーワードをエスケープして'|'で連結（部分一致のため境界は不要）
            escaped_keywords = [re.escape(keyword) for keyword in keywords]
            pattern_str = "|".join(escaped_keywords)

            try:
                # re.IGNORECASE は日本語キーワードには効果がありませんが、
                # 英語キーワード（例: 'BBQ'）の大文字小文字を区別しないために付与しています。
                compiled_pattern = re.compile(pattern_str, re.IGNORECASE)
                compiled_patterns[level] = compiled_pattern
                logger.debug(f"📋 Compiled {level} priority pattern with {len(keywords)} keywords")
            except re.error as e:
                logger.error(f"❌ Failed to compile {level} priority pattern: {e}")
                # 個別パターンでエラーが発生しても他のレベルは続行

        return compiled_patterns

    def _load_quote_comments(
        self,
    ) -> "tuple[List[tuple[str, List[str]]], List[str], List[str], List[str]]":
        """
        引用コメント文言を読み込む

        data/quote_comments.tsv（非公開スプレッドシート由来、gitignore対象）が存在すればそこから
        読み込み、存在しなければ最小限のフォールバック（クラス定数）を使用する。

        ファイル形式（タブ区切り、ヘッダー行あり）: bucket, keyword, text
            - bucket: "specific" | "high" | "medium" | "default"
            - keyword: bucket="specific" の時のみ使用（マッチしたキーワードとの照合に使う）
            - text: コメント本文（絵文字は含めない。付与は _decorate_comment() が一元的に行う）

        Returns:
            (specific_keyword_comments, high_priority_comments,
             medium_priority_comments, default_quote_comments) のタプル
        """
        if not Path(self.QUOTE_COMMENTS_FILE).exists():
            logger.warning(
                f"⚠️ 引用コメントファイルが見つかりませんでした: {self.QUOTE_COMMENTS_FILE}。"
                "最小限のフォールバック文言を使用します。非公開スプレッドシートからエクスポートしてください。"
            )
            return (
                list(self._FALLBACK_SPECIFIC_KEYWORD_COMMENTS),
                list(self._FALLBACK_HIGH_PRIORITY_COMMENTS),
                list(self._FALLBACK_MEDIUM_PRIORITY_COMMENTS),
                list(self._FALLBACK_DEFAULT_QUOTE_COMMENTS),
            )

        specific_map: Dict[str, List[str]] = {}
        high: List[str] = []
        medium: List[str] = []
        default: List[str] = []

        try:
            with open(self.QUOTE_COMMENTS_FILE, encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    bucket = (row.get("bucket") or "").strip()
                    keyword = (row.get("keyword") or "").strip()
                    text = (row.get("text") or "").strip()
                    if not bucket or not text:
                        continue

                    if bucket == "specific" and keyword:
                        specific_map.setdefault(keyword, []).append(text)
                    elif bucket == "high":
                        high.append(text)
                    elif bucket == "medium":
                        medium.append(text)
                    elif bucket == "default":
                        default.append(text)

            specific = list(specific_map.items())

            # 空のバケットはフォールバックで補完（部分的にしか記入されていない場合の保険）
            if not specific:
                specific = list(self._FALLBACK_SPECIFIC_KEYWORD_COMMENTS)
            if not high:
                high = list(self._FALLBACK_HIGH_PRIORITY_COMMENTS)
            if not medium:
                medium = list(self._FALLBACK_MEDIUM_PRIORITY_COMMENTS)
            if not default:
                default = list(self._FALLBACK_DEFAULT_QUOTE_COMMENTS)

            logger.info(
                f"✅ 引用コメントを読み込みました: specific={len(specific)}, "
                f"high={len(high)}, medium={len(medium)}, default={len(default)}"
            )
            return specific, high, medium, default

        except Exception as e:
            logger.error(f"❌ Failed to load quote comments from {self.QUOTE_COMMENTS_FILE}: {e}")
            return (
                list(self._FALLBACK_SPECIFIC_KEYWORD_COMMENTS),
                list(self._FALLBACK_HIGH_PRIORITY_COMMENTS),
                list(self._FALLBACK_MEDIUM_PRIORITY_COMMENTS),
                list(self._FALLBACK_DEFAULT_QUOTE_COMMENTS),
            )

    def _decorate_comment(self, text: str, is_meat_topic: bool) -> str:
        """
        絵文字ルールを一元適用する

        🐻を署名として文頭に1つ付与し、肉トピックの時のみ🥩🍖のどちらか1つを末尾に添える。
        それ以外の装飾絵文字は付与しない（docs/CHARACTER_PERSONA_SAMPLE.md 絵文字ルール参照）。

        Args:
            text: 絵文字を含まない素のコメント本文
            is_meat_topic: マッチしたキーワードにお肉語彙が含まれるか

        Returns:
            絵文字ルール適用後のコメント文字列
        """
        prefix = "🐻 "
        suffix = f" {random.choice(('🥩', '🍖'))}" if is_meat_topic else ""
        return f"{prefix}{text}{suffix}"

    def generate_tweet_content(self, category: Optional[str] = None, tone: Optional[str] = None) -> Optional[str]:
        """
        ツイートコンテンツを生成

        Args:
            category: カテゴリ（お肉、日常、季節等）
            tone: トーン（可愛い、元気、癒し等）

        Returns:
            生成されたツイート内容（Noneの場合は生成失敗）
        """
        try:
            # 使用可能なテンプレートを取得
            template = self.db_manager.get_available_template(category, tone)

            if not template:
                logger.warning("⚠️ No available templates found")
                return None

            # テンプレートからツイート内容を生成
            tweet_content = self._process_template(template)

            if not tweet_content:
                logger.warning("⚠️ Failed to process template")
                return None

            # 使用履歴を記録
            self.db_manager.record_tweet_usage(int(template["id"]), tweet_content)

            logger.info(f"🎲 Generated tweet content: Template ID={template['id']}")
            return tweet_content

        except Exception as e:
            logger.error(f"❌ Failed to generate tweet content: {e}")
            return None

    def _process_template(self, template: Dict[str, str]) -> Optional[str]:
        """
        テンプレートを処理してツイート内容を生成

        Args:
            template: テンプレート辞書

        Returns:
            処理されたツイート内容
        """
        try:
            base_template = template["template"]

            # 動的要素を追加
            processed_content = self._add_dynamic_elements(base_template)

            # 文字数チェック（280文字以下に短縮）
            # 注意: textwrap.shorten()は単語境界で切り詰めるため、日本語（スペースなし）では
            # 期待通りに動作しない可能性がある。そのため、直接文字列を切り詰める方式を採用。
            # TODO: Twitterの文字数カウントは結合文字や絵文字を考慮した特殊なロジックを使用するため、
            # より正確な文字数制限を守るには twitter-text-parser ライブラリの使用を検討。
            if _safe_text_length(processed_content) > 280:
                logger.warning(f"Tweet too long ({_safe_text_length(processed_content)} chars), truncating...")
                # 277文字 + "..." = 280文字以内に収まるよう切り詰め
                # 注意: この方法はTwitterの正確な文字数カウント（結合文字・絵文字考慮）を反映していない
                processed_content = processed_content[:277] + "..."

            return processed_content

        except Exception as e:
            logger.error(f"❌ Failed to process template: {e}")
            return None

    def _add_dynamic_elements(self, template: str) -> str:
        """
        テンプレートに動的要素を追加

        Args:
            template: ベーステンプレート

        Returns:
            動的要素が追加されたテンプレート
        """
        try:
            # 現在時刻の取得
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            current_hour = now.hour

            # 時間帯に応じた挨拶
            if 5 <= current_hour < 12:
                greeting = "おはよう"
            elif 12 <= current_hour < 18:
                greeting = "こんにちは"
            else:
                greeting = "こんばんは"

            # 動的要素の置換
            dynamic_content = template

            # プレースホルダーの置換
            replacements = {
                "{time}": current_time,
                "{greeting}": greeting,
                "{hour}": str(current_hour),
                "{emoji}": self._get_random_emoji(),
                "{weather}": self._get_weather_emoji(),
            }

            for placeholder, value in replacements.items():
                dynamic_content = dynamic_content.replace(placeholder, value)

            return dynamic_content

        except Exception as e:
            logger.error(f"❌ Failed to add dynamic elements: {e}")
            return template

    def _get_random_emoji(self) -> str:
        """ランダムな絵文字を取得"""
        emojis = ["🐻", "🍖", "🥩", "🔥", "✨", "💕", "🌟", "😊", "🤗", "💖"]
        return random.choice(emojis)

    def _get_weather_emoji(self) -> str:
        """天気に応じた絵文字を取得（簡易版）"""
        # 実際の天気APIと連携する場合はここを拡張
        weather_emojis = ["☀️", "⛅", "🌧️", "❄️", "🌈"]
        return random.choice(weather_emojis)

    def get_content_stats(self) -> Dict[str, str]:
        """
        コンテンツ生成統計を取得

        Returns:
            統計情報
        """
        try:
            # 全テンプレートを取得
            all_templates = self.db_manager.get_templates(active_only=True)

            # カテゴリ別統計
            category_stats: Dict[str, str] = {}
            tone_stats: Dict[str, str] = {}

            for template in all_templates:
                category = template["category"]
                tone = template["tone"]

                # カテゴリ統計
                if category not in category_stats:
                    category_stats[category] = "0"
                category_stats[category] = str(int(category_stats[category]) + 1)

                # トーン統計
                if tone not in tone_stats:
                    tone_stats[tone] = "0"
                tone_stats[tone] = str(int(tone_stats[tone]) + 1)

            stats = {
                "total_templates": str(len(all_templates)),
                "categories": str(category_stats),
                "tones": str(tone_stats),
                "generated_at": datetime.now().isoformat(),
            }

            logger.info(f"📊 Content stats retrieved: {len(all_templates)} templates")
            return stats

        except Exception as e:
            logger.error(f"❌ Failed to get content stats: {e}")
            return {"error": str(e)}

    def add_sample_templates(self) -> int:
        """サンプルテンプレートを追加（テスト用）"""
        try:
            sample_templates = [
                {
                    "category": "お肉",
                    "tone": "可愛い",
                    "template": "🐻 {greeting}！今日のお肉は最高だよ〜 {emoji}",
                },
                {
                    "category": "お肉",
                    "tone": "元気",
                    "template": "🍖 お肉パワーで今日も頑張るぞ！{time}だよ〜",
                },
                {
                    "category": "お肉",
                    "tone": "癒し",
                    "template": "🥩 お肉を食べると心が温かくなるね {emoji} {greeting}",
                },
                {
                    "category": "日常",
                    "tone": "可愛い",
                    "template": "🐻 {greeting}！今日も{emoji}で頑張ろうね",
                },
                {
                    "category": "季節",
                    "tone": "元気",
                    "template": "✨ {weather}の日はお肉が美味しいね！{time}だよ〜",
                },
            ]

            added_count = 0
            for template_data in sample_templates:
                try:
                    template_id = self.db_manager.add_template(
                        template_data["category"],
                        template_data["tone"],
                        template_data["template"],
                    )
                    added_count += 1
                    logger.info(f"✅ Sample template added: ID={template_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to add sample template: {e}")

            logger.info(f"🎉 Added {added_count} sample templates")
            return added_count

        except Exception as e:
            logger.error(f"❌ Failed to add sample templates: {e}")
            return 0

    def close(self) -> None:
        """リソースを解放"""
        try:
            if self.db_manager:
                self.db_manager.close()
            logger.info("✅ Content generator closed")
        except Exception as e:
            logger.error(f"❌ Error closing content generator: {e}")

    def __enter__(self) -> "ContentGenerator":
        """コンテキストマネージャー用"""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """コンテキストマネージャー用"""
        self.close()

    def is_meat_related_tweet(self, text: str) -> bool:
        """
        お肉関連ツイートかどうか判定する。

        仕様:
            - まずNGワードフィルタリング（事前コンパイル済み正規表現パターン）を先に実行し、NGワードが含まれていればFalseを返す。
            - NGワードに該当しない場合、「お肉」関連キーワード（self.MEAT_KEYWORDS）を部分一致で検出する。
                - 部分一致とする理由は、「焼肉」「肉まん」「お肉」など「肉」を含む複合語も検出したいため。
                - NGワードと異なり単語境界は考慮しない。
            - MEAT_KEYWORDSが大幅に増加した場合は、パフォーマンスのため正規表現パターンの事前コンパイルを検討すること。

        Args:
            text (str): 判定対象のツイート本文

        Returns:
            bool: お肉関連ツイートの場合True、そうでなければFalse
        """
        try:
            # NGワードチェック
            if self._ng_pattern and self._ng_pattern.search(text):
                logger.debug(f"🚫 NGワード検出 in '{text[:50]}...'")
                return False

            # お肉キーワード部分一致チェック
            return any(keyword in text for keyword in self.MEAT_KEYWORDS)

        except Exception as e:
            logger.error(f"❌ Error checking meat keywords: {e}")
            return False

    def is_food_related_tweet(self, text: str) -> bool:
        """
        食関連（お肉＋食・レストラン全般）ツイートかどうか判定する。

        is_meat_related_tweet()の一般化版。判定ロジックはお肉限定版と同様だが、
        事前コンパイル済みの正規表現パターン（self._food_patterns）を使う点が異なる
        （get_food_keyword_score()と同じ最適化を流用し、キーワード増加時のスキャン
        コストを抑える）。

        Args:
            text (str): 判定対象のツイート本文

        Returns:
            bool: 食関連ツイートの場合True、そうでなければFalse
        """
        try:
            # NGワードチェック
            if self._ng_pattern and self._ng_pattern.search(text):
                logger.debug(f"🚫 NGワード検出 in '{text[:50]}...'")
                return False

            # 事前コンパイル済み正規表現を使用（パフォーマンス向上）
            if self._food_patterns:
                return any(pattern.search(text) for pattern in self._food_patterns.values())

            # フォールバック版: パターンのコンパイルに失敗している場合のみ文字列検索
            all_food_keywords = [kw for v in self._combined_keywords_priority.values() for kw in v["keywords"]]
            return any(keyword in text for keyword in all_food_keywords)

        except Exception as e:
            logger.error(f"❌ Error checking food keywords: {e}")
            return False

    def get_food_keyword_score(self, text: str) -> Dict[str, Any]:
        """
        食関連（お肉＋食・レストラン全般）ツイートの優先度スコアを計算（正規表現最適化版）

        Args:
            text (str): 判定対象のツイート本文

        Returns:
            Dict[str, Any]: スコア情報を含む辞書
                - is_food_related: bool - 食関連かどうか
                - score: int - 優先度スコア（0-3、3が最高）
                - matched_keywords: List[str] - マッチしたキーワードリスト
                - highest_priority_level: str - 最高優先度レベル
                - is_meat_topic: bool - マッチしたキーワードにお肉語彙が含まれるか（絵文字ルール判定用）
        """
        try:
            # NGワードチェック（事前コンパイル済み正規表現使用）
            if self._ng_pattern and self._ng_pattern.search(text):
                logger.debug(f"🚫 NGワード検出 in '{text[:50]}...'")
                return {
                    "is_food_related": False,
                    "score": 0,
                    "matched_keywords": [],
                    "highest_priority_level": "NONE",
                    "ng_word_detected": True,
                    "is_meat_topic": False,
                }

            matched_keywords = []
            max_priority = 0
            highest_priority_level = "NONE"

            # 事前コンパイル済み正規表現を使用（パフォーマンス向上）
            if self._food_patterns:
                # 最適化版: 正規表現パターンマッチング
                for level, pattern in self._food_patterns.items():
                    matches = pattern.findall(text)
                    if matches:
                        priority_data = self._combined_keywords_priority[level]
                        priority = int(priority_data["priority"])
                        matched_keywords.extend(matches)

                        if priority > max_priority:
                            max_priority = priority
                            highest_priority_level = level
            else:
                # フォールバック版: 文字列検索
                logger.debug("🔄 Using fallback string matching for food keywords")
                for level, priority_data in self._combined_keywords_priority.items():
                    keywords: list[str] = priority_data["keywords"]
                    level_priority: int = priority_data["priority"]

                    for keyword in keywords:
                        if keyword in text:
                            matched_keywords.append(keyword)
                            if level_priority > max_priority:
                                max_priority = level_priority
                                highest_priority_level = level

            is_food_related = len(matched_keywords) > 0
            deduped_keywords = list(set(matched_keywords))
            is_meat_topic = any(keyword in self._meat_keyword_set for keyword in deduped_keywords)

            if is_food_related:
                logger.debug(
                    f"🍽️ Food keywords detected: {matched_keywords} "
                    f"(Priority: {highest_priority_level}, Score: {max_priority}, Meat topic: {is_meat_topic})"
                )

            return {
                "is_food_related": is_food_related,
                "score": max_priority,
                "matched_keywords": deduped_keywords,  # 重複除去
                "highest_priority_level": highest_priority_level,
                "ng_word_detected": False,
                "is_meat_topic": is_meat_topic,
            }

        except Exception as e:
            logger.error(f"❌ Error calculating food keyword score: {e}")
            return {
                "is_food_related": False,
                "score": 0,
                "matched_keywords": [],
                "highest_priority_level": "NONE",
                "ng_word_detected": False,
                "is_meat_topic": False,
            }

    def generate_quote_comment(self, original_tweet_text: str) -> str:
        """食関連ツイート用のコメント生成（優先度対応版）"""
        try:
            # キーワードの優先度スコアを取得
            score_info = self.get_food_keyword_score(original_tweet_text)

            if not score_info["is_food_related"]:
                logger.warning("⚠️ Trying to generate comment for non-food-related tweet")
                return self._decorate_comment("肉ね！", is_meat_topic=True)  # フォールバック

            # 優先度レベルに基づいてコメント選択（絵文字を含まない素のテキスト）
            base_comment = self._select_comment_by_priority(
                score_info["highest_priority_level"], score_info["matched_keywords"], original_tweet_text
            )

            # 時間帯に応じた追加コメント
            current_hour = datetime.now().hour
            time_comment = self._get_time_based_comment(current_hour, score_info["score"])

            # 絵文字ルールを一元適用（🐻署名＋肉トピック時のみ🥩🍖）
            final_comment = self._decorate_comment(base_comment + time_comment, score_info["is_meat_topic"])

            logger.info(f"✅ Generated quote comment: {final_comment}")
            logger.info(f"📝 Priority: {score_info['highest_priority_level']} (Score: {score_info['score']})")
            logger.info(f"📝 Keywords: {score_info['matched_keywords']}")
            logger.info(f"📝 Based on: {original_tweet_text[:50]}...")
            return final_comment

        except Exception as e:
            logger.error(f"❌ Error generating quote comment: {e}")
            return self._decorate_comment("肉ね！", is_meat_topic=True)  # フォールバック

    def _select_comment_by_priority(self, priority_level: str, matched_keywords: List[str], original_text: str) -> str:
        """
        優先度レベルに基づいてコメントを選択（絵文字を含まない素のテキストを返す）

        絵文字の付与は行わない。呼び出し元（generate_quote_comment）が
        _decorate_comment() で一元的に絵文字ルールを適用する。
        """
        try:
            # 特定キーワードに対する専用コメント（優先度レベルより先に判定する。
            # HIGH優先度キーワードの多くはこちらの対象でもあるため、先に判定しないと
            # 専用コメントが選ばれることがなくなってしまう）
            for keyword, comments in self._specific_keyword_comments:
                if keyword in matched_keywords:
                    return random.choice(comments)

            # 高優先度キーワード用の特別なコメント
            if priority_level == "HIGH":
                return random.choice(self._high_priority_comments)

            # 中優先度用のコメント
            if priority_level == "MEDIUM":
                return random.choice(self._medium_priority_comments)

            # 低優先度・デフォルト用のコメント
            return random.choice(self._default_quote_comments)

        except Exception as e:
            logger.error(f"❌ Error selecting comment by priority: {e}")
            return random.choice(self._default_quote_comments)

    def _get_time_based_comment(self, current_hour: int, priority_score: int) -> str:
        """時間帯と優先度に基づいて追加コメントを生成（絵文字を含まない素のテキスト）"""
        try:
            base_time_comment = ""

            if self.MORNING_START <= current_hour < self.MORNING_END:
                base_time_comment = " 朝から幸せね〜"
            elif self.LUNCH_START <= current_hour < self.LUNCH_END:
                base_time_comment = " お昼にちょうどいいわね！"
            elif self.DINNER_START <= current_hour < self.DINNER_END:
                base_time_comment = " 夜ご飯が楽しみだ！"
            else:
                # 夜間や早朝の場合、優先度が高ければ特別コメント
                if priority_score >= 3:
                    base_time_comment = " 特別ね〜！"
                elif priority_score >= 2:
                    base_time_comment = " たまらないわね！"

            return base_time_comment

        except Exception as e:
            logger.error(f"❌ Error generating time-based comment: {e}")
            return ""


# テスト用関数
def test_content_generator() -> None:
    """コンテンツジェネレーターのテスト実行"""
    print(f"🐻 {BOT_NAME} Content generator test starting...")

    try:
        with ContentGenerator() as generator:
            # サンプルテンプレートを追加
            added_count = generator.add_sample_templates()
            print(f"✅ Added {added_count} sample templates")

            # コンテンツ生成テスト
            for i in range(3):
                content = generator.generate_tweet_content()
                if content:
                    print(f"✅ Generated content {i+1}: {content}")
                else:
                    print(f"❌ Failed to generate content {i+1}")

            # カテゴリ指定テスト
            meat_content = generator.generate_tweet_content(category="お肉")
            if meat_content:
                print(f"✅ Generated meat content: {meat_content}")

            # 統計情報取得
            stats = generator.get_content_stats()
            print(f"✅ Content stats: {stats}")

            print("🎉 Content generator test completed successfully!")

    except Exception as e:
        print(f"❌ Content generator test failed: {e}")


if __name__ == "__main__":
    test_content_generator()
