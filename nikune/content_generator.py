"""
nikune bot content generator
お肉コメント生成機能（SQLite + Redis連携）
"""

import logging
import random
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Pattern

from config.settings import BOT_NAME, NG_KEYWORDS, TIME_SETTINGS

from .database import DatabaseManager

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ContentGenerator:
    """コンテンツ生成クラス"""

    # お肉関連キーワード（クラス定数）
    MEAT_KEYWORDS = [
        "肉",
        "お肉",
        "焼肉",
        "ステーキ",
        "ハンバーグ",
        "すき焼き",
        "しゃぶしゃぶ",
        "牛肉",
        "豚肉",
        "鶏肉",
        "ラム肉",
        "ジンギスカン",
        "バーベキュー",
        "BBQ",
        "焼き鳥",
        "唐揚げ",
        "とんかつ",
        "牛丼",
        "豚丼",
        "焼き豚",
        "ローストビーフ",
        "ミートボール",
        "ハンバーガー",
        "チキン",
        "ポーク",
        "ビーフ",
        "肉汁",
    ]

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
        self._ng_patterns = self._compile_ng_patterns()

        logger.info(f"✅ {self.bot_name} Content generator initialized")

    def _compile_ng_patterns(self) -> List[Pattern[str]]:
        """NGワードの正規表現パターンを事前にコンパイル"""
        patterns = []
        for ng_word in self.NG_KEYWORDS:
            pattern = rf"(?:^|{self.WORD_BOUNDARY_PATTERN}){re.escape(ng_word)}(?:{self.WORD_BOUNDARY_PATTERN}|$)"
            patterns.append(re.compile(pattern))
        logger.debug(f"📋 Compiled {len(patterns)} NG word patterns")
        return patterns

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

            # 文字数チェック（280文字制限）
            if len(processed_content) > 280:
                logger.warning(f"Tweet too long ({len(processed_content)} chars), truncating...")
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
        """お肉関連ツイートかどうか判定"""
        try:
            # NGワードチェック（事前コンパイル済みパターンを使用）
            # パフォーマンス最適化のため、初期化時にコンパイルしたパターンを使用
            for i, pattern in enumerate(self._ng_patterns):
                if pattern.search(text):
                    ng_word = self.NG_KEYWORDS[i]
                    logger.debug(f"🚫 NGワード検出: '{ng_word}' in '{text[:50]}...'")
                    return False

            # お肉キーワードチェック（部分一致で十分）
            return any(keyword in text for keyword in self.MEAT_KEYWORDS)

        except Exception as e:
            logger.error(f"❌ Error checking meat keywords: {e}")
            return False

    def generate_quote_comment(self, original_tweet_text: str) -> str:
        """お肉関連ツイート用のコメント生成"""
        try:
            # 優先度順でキーワードマッチング（最初にマッチしたものを使用）
            for keyword, comments in self.SPECIFIC_KEYWORD_COMMENTS:
                if keyword in original_tweet_text:
                    base_comment = random.choice(comments)
                    break
            else:
                # デフォルトのnikune風コメントテンプレート
                base_comment = random.choice(self.DEFAULT_QUOTE_COMMENTS)

            # 時間帯に応じた追加コメント
            current_hour = datetime.now().hour

            if self.MORNING_START <= current_hour < self.MORNING_END:
                time_comment = " 朝からお肉いいですね〜"
            elif self.LUNCH_START <= current_hour < self.LUNCH_END:
                time_comment = " お昼のお肉タイム！"
            elif self.DINNER_START <= current_hour < self.DINNER_END:
                time_comment = " 夕食が楽しみになります！"
            else:
                time_comment = ""

            final_comment = base_comment + time_comment

            logger.info(f"✅ Generated quote comment: {final_comment}")
            logger.info(f"📝 Based on original text: {original_tweet_text[:50]}...")
            return final_comment

        except Exception as e:
            logger.error(f"❌ Error generating quote comment: {e}")
            return "🐻 お肉〜！"  # フォールバック


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
