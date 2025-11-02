"""
nikune bot content generator
お肉コメント生成機能（SQLite + Redis連携）
"""

import logging
import random
import re
import textwrap
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.settings import BOT_NAME, NG_KEYWORDS, TIME_SETTINGS

from .database import DatabaseManager

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

    # 後方互換性のため、従来のMEAT_KEYWORDSも維持
    MEAT_KEYWORDS: list[str] = []
    for priority_data in MEAT_KEYWORDS_PRIORITY.values():
        MEAT_KEYWORDS.extend(priority_data["keywords"])

    # NGワード（設定ファイルから読み込み）
    NG_KEYWORDS = NG_KEYWORDS

    # キーワード別コメントテンプレート（優先度順）
    SPECIFIC_KEYWORD_COMMENTS = [
        ("ステーキ", ["🥩 ステーキ美味しそう！", "🔥 ステーキ最高ですね！"]),
        ("焼肉", ["🍖 焼肉いいな〜！", "🐻 焼肉パーティー楽しそう！"]),
        ("ハンバーグ", ["🍴 ハンバーグ食べたい！", "😋 ジューシーで美味しそう！"]),
        ("BBQ", ["🔥 BBQ楽しそう！", "🥩 アウトドアでお肉最高！"]),
        ("バーベキュー", ["🔥 BBQ楽しそう！", "🥩 アウトドアでお肉最高！"]),
    ]

    # デフォルトコメントテンプレート
    DEFAULT_QUOTE_COMMENTS = [
        "🐻 おいしそう！",
        "🥩 お肉だ〜！食べたい！",
        "😋 これは美味しそうですね〜",
        "🤤 お肉愛が伝わってきます！",
        "🐻💕 素敵なお肉ですね！",
        "🥩✨ 美味しそうで羨ましいです！",
        "🍴 いいですね〜食べてみたい！",
        "🐻🥩 お肉最高〜！",
        "😍 とても美味しそう！",
        "🥩🔥 素晴らしいお肉ですね！",
    ]

    # 時間帯判定用設定（config/settings.pyから読み込み）
    MORNING_START = TIME_SETTINGS["MORNING_START"]
    MORNING_END = TIME_SETTINGS["MORNING_END"]
    LUNCH_START = TIME_SETTINGS["LUNCH_START"]
    LUNCH_END = TIME_SETTINGS["LUNCH_END"]
    DINNER_START = TIME_SETTINGS["DINNER_START"]
    DINNER_END = TIME_SETTINGS["DINNER_END"]

    # 正規表現パターン定数（可読性向上のため分割定義）
    # 日本語文字クラス: ひらがな、カタカナ、漢字（拡張Aも含む）
    JAPANESE_CHARS = r"\u3040-\u309F\u30A0-\u30FF\u3400-\u4DBF\u4E00-\u9FFF"
    # 単語境界パターン: 英数字または日本語文字以外
    WORD_BOUNDARY_PATTERN = rf"[^\w{JAPANESE_CHARS}]"

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
        except Exception as e:
            logger.error(f"❌ Failed to compile NG pattern: {e}")
            # フォールバック: Noneを使用（NGワード機能を無効化）
            self._ng_pattern = None
            logger.warning("⚠️ NG word filtering disabled due to pattern compilation failure")

        # お肉キーワードの正規表現パターンを事前コンパイル（パフォーマンス最適化v2）
        try:
            self._meat_patterns: Dict[str, re.Pattern[str]] = self._compile_meat_patterns()
            logger.info("✅ Meat keyword patterns pre-compiled for better performance")
        except Exception as e:
            logger.error(f"❌ Failed to compile meat patterns: {e}")
            self._meat_patterns = {}
            logger.warning("⚠️ Using fallback string matching for meat keywords")

        logger.info(f"✅ {self.bot_name} Content generator initialized")

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

        # 前方・後方境界を含めたパターンを組み立て
        prefix = rf"(?:^|{self.WORD_BOUNDARY_PATTERN})"
        suffix = rf"(?:{self.WORD_BOUNDARY_PATTERN}|$)"
        pattern = f"{prefix}(?:{'|'.join(words)}){suffix}"

        compiled = re.compile(pattern)
        logger.debug(f"📋 Compiled unified NG word pattern with {len(self.NG_KEYWORDS)} keywords")
        return compiled

    def _compile_meat_patterns(self) -> Dict[str, re.Pattern[str]]:
        """
        お肉キーワードの正規表現パターンを優先度別に事前コンパイル

        Returns:
            優先度レベル別のコンパイル済み正規表現パターン辞書

        Raises:
            re.error: 正規表現のコンパイルに失敗した場合
        """
        compiled_patterns = {}

        for level, priority_data in self.MEAT_KEYWORDS_PRIORITY.items():
            keywords: list[str] = priority_data["keywords"]
            if not keywords:
                continue

            # キーワードをエスケープして'|'で連結（部分一致のため境界は不要）
            escaped_keywords = [re.escape(keyword) for keyword in keywords]
            pattern_str = "|".join(escaped_keywords)

            try:
                # re.IGNORECASE は日本語キーワードには効果がありませんが、英語キーワード（例: 'BBQ'）の大文字小文字を区別しないために付与しています。
                compiled_pattern = re.compile(pattern_str, re.IGNORECASE)
                compiled_patterns[level] = compiled_pattern
                logger.debug(f"📋 Compiled {level} priority pattern with {len(keywords)} keywords")
            except re.error as e:
                logger.error(f"❌ Failed to compile {level} priority pattern: {e}")
                # 個別パターンでエラーが発生しても他のレベルは続行

        return compiled_patterns

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

            # 文字数チェック（280文字以下に短縮）- textwrapでUnicode/絵文字安全な切り詰め
            if len(processed_content) > 280:
                logger.warning(f"Tweet too long ({len(processed_content)} chars), truncating...")
                processed_content = textwrap.shorten(processed_content, width=280, placeholder="...")

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

    def get_meat_keyword_score(self, text: str) -> Dict[str, Any]:
        """
        お肉関連ツイートの優先度スコアを計算（正規表現最適化版）

        Args:
            text (str): 判定対象のツイート本文

        Returns:
            Dict[str, Any]: スコア情報を含む辞書
                - is_meat_related: bool - お肉関連かどうか
                - score: int - 優先度スコア（0-3、3が最高）
                - matched_keywords: List[str] - マッチしたキーワードリスト
                - highest_priority_level: str - 最高優先度レベル
        """
        try:
            # NGワードチェック（事前コンパイル済み正規表現使用）
            if self._ng_pattern and self._ng_pattern.search(text):
                logger.debug(f"🚫 NGワード検出 in '{text[:50]}...'")
                return {
                    "is_meat_related": False,
                    "score": 0,
                    "matched_keywords": [],
                    "highest_priority_level": "NONE",
                    "ng_word_detected": True,
                }

            matched_keywords = []
            max_priority = 0
            highest_priority_level = "NONE"

            # 事前コンパイル済み正規表現を使用（パフォーマンス向上）
            if self._meat_patterns:
                # 最適化版: 正規表現パターンマッチング
                for level, pattern in self._meat_patterns.items():
                    matches = pattern.findall(text)
                    if matches:
                        priority_data = self.MEAT_KEYWORDS_PRIORITY[level]
                        priority = int(priority_data["priority"])
                        matched_keywords.extend(matches)

                        if priority > max_priority:
                            max_priority = priority
                            highest_priority_level = level
            else:
                # フォールバック版: 文字列検索
                logger.debug("🔄 Using fallback string matching for meat keywords")
                for level, priority_data in self.MEAT_KEYWORDS_PRIORITY.items():
                    keywords: list[str] = priority_data["keywords"]
                    level_priority: int = priority_data["priority"]

                    for keyword in keywords:
                        if keyword in text:
                            matched_keywords.append(keyword)
                            if level_priority > max_priority:
                                max_priority = level_priority
                                highest_priority_level = level

            is_meat_related = len(matched_keywords) > 0

            if is_meat_related:
                logger.debug(
                    f"🥩 Meat keywords detected: {matched_keywords} "
                    f"(Priority: {highest_priority_level}, Score: {max_priority})"
                )

            return {
                "is_meat_related": is_meat_related,
                "score": max_priority,
                "matched_keywords": list(set(matched_keywords)),  # 重複除去
                "highest_priority_level": highest_priority_level,
                "ng_word_detected": False,
            }

        except Exception as e:
            logger.error(f"❌ Error calculating meat keyword score: {e}")
            return {
                "is_meat_related": False,
                "score": 0,
                "matched_keywords": [],
                "highest_priority_level": "NONE",
                "ng_word_detected": False,
            }

    def generate_quote_comment(self, original_tweet_text: str) -> str:
        """お肉関連ツイート用のコメント生成（優先度対応版）"""
        try:
            # キーワードの優先度スコアを取得
            score_info = self.get_meat_keyword_score(original_tweet_text)

            if not score_info["is_meat_related"]:
                logger.warning("⚠️ Trying to generate comment for non-meat-related tweet")
                return "🐻 お肉〜！"  # フォールバック

            # 優先度レベルに基づいてコメント選択
            base_comment = self._select_comment_by_priority(
                score_info["highest_priority_level"], score_info["matched_keywords"], original_tweet_text
            )

            # 時間帯に応じた追加コメント
            current_hour = datetime.now().hour
            time_comment = self._get_time_based_comment(current_hour, score_info["score"])

            final_comment = base_comment + time_comment

            logger.info(f"✅ Generated quote comment: {final_comment}")
            logger.info(f"📝 Priority: {score_info['highest_priority_level']} (Score: {score_info['score']})")
            logger.info(f"📝 Keywords: {score_info['matched_keywords']}")
            logger.info(f"📝 Based on: {original_tweet_text[:50]}...")
            return final_comment

        except Exception as e:
            logger.error(f"❌ Error generating quote comment: {e}")
            return "🐻 お肉〜！"  # フォールバック

    def _select_comment_by_priority(self, priority_level: str, matched_keywords: List[str], original_text: str) -> str:
        """優先度レベルに基づいてコメントを選択"""
        try:
            # 高優先度キーワード用の特別なコメント
            if priority_level == "HIGH":
                high_priority_comments = [
                    "🥩✨ 素晴らしいお肉料理ですね！",
                    "😍 高級感あふれるお肉！羨ましいです！",
                    "🐻💕 これは贅沢なお肉ですね〜",
                    "🔥 最高級のお肉！とても美味しそう！",
                    "🥩👑 特別なお肉料理に感動です！",
                ]
                return random.choice(high_priority_comments)

            # 特定キーワードに対する専用コメント
            for keyword, comments in self.SPECIFIC_KEYWORD_COMMENTS:
                if keyword in matched_keywords:
                    return random.choice(comments)

            # 中優先度用のコメント
            if priority_level == "MEDIUM":
                medium_priority_comments = [
                    "🥩 美味しそうなお肉ですね！",
                    "🐻 お肉愛が伝わってきます！",
                    "😋 これは食べてみたいです〜",
                    "🍴 素敵なお肉料理ですね！",
                    "🥩🔥 お肉最高！",
                ]
                return random.choice(medium_priority_comments)

            # 低優先度・デフォルト用のコメント
            return random.choice(self.DEFAULT_QUOTE_COMMENTS)

        except Exception as e:
            logger.error(f"❌ Error selecting comment by priority: {e}")
            return random.choice(self.DEFAULT_QUOTE_COMMENTS)

    def _get_time_based_comment(self, current_hour: int, priority_score: int) -> str:
        """時間帯と優先度に基づいて追加コメントを生成"""
        try:
            base_time_comment = ""

            if self.MORNING_START <= current_hour < self.MORNING_END:
                base_time_comment = " 朝からお肉いいですね〜"
            elif self.LUNCH_START <= current_hour < self.LUNCH_END:
                base_time_comment = " お昼のお肉タイム！"
            elif self.DINNER_START <= current_hour < self.DINNER_END:
                base_time_comment = " 夕食が楽しみになります！"
            else:
                # 夜間や早朝の場合、優先度が高ければ特別コメント
                if priority_score >= 3:
                    base_time_comment = " 特別なお肉ですね〜！"
                elif priority_score >= 2:
                    base_time_comment = " お肉好きにはたまらないです！"

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
