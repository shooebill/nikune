import re
from unittest import TestCase, mock

from nikune.content_generator import ContentGenerator

# 絵文字ルール（docs/CHARACTER_PERSONA_SAMPLE.md）で禁止されている装飾絵文字
FORBIDDEN_DECORATIVE_EMOJI = ["✨", "😍", "🤤", "😋", "🔥", "💕", "🌟", "😊", "🤗", "💖", "👑"]
MEAT_EMOJI = {"🥩", "🍖"}


def _make_generator() -> ContentGenerator:
    # DB接続（Redis/SQLite）は不要なロジックのみを検証するため、db_managerはダミーで渡す
    return ContentGenerator(db_manager=mock.MagicMock())


class FoodKeywordDetectionTests(TestCase):
    def setUp(self) -> None:
        self.generator = _make_generator()

    def test_existing_meat_keywords_still_detected_by_level(self) -> None:
        cases = [
            ("ステーキ食べた", "HIGH", 3),
            ("焼肉最高", "HIGH", 3),
            ("お肉美味しい", "MEDIUM", 2),
            ("唐揚げ食べたい", "LOW", 1),
        ]
        for text, expected_level, expected_score in cases:
            with self.subTest(text=text):
                result = self.generator.get_food_keyword_score(text)
                self.assertTrue(result["is_food_related"])
                self.assertEqual(result["highest_priority_level"], expected_level)
                self.assertEqual(result["score"], expected_score)
                self.assertTrue(result["is_meat_topic"])

    def test_new_food_keywords_detected_by_level(self) -> None:
        cases = [
            ("寿司食べたい", "HIGH", 3),
            ("カレー美味しい", "MEDIUM", 2),
            ("お弁当買った", "LOW", 1),
        ]
        for text, expected_level, expected_score in cases:
            with self.subTest(text=text):
                result = self.generator.get_food_keyword_score(text)
                self.assertTrue(result["is_food_related"])
                self.assertEqual(result["highest_priority_level"], expected_level)
                self.assertEqual(result["score"], expected_score)
                self.assertFalse(result["is_meat_topic"])

    def test_mixed_meat_and_food_keywords_take_higher_priority(self) -> None:
        result = self.generator.get_food_keyword_score("ステーキとカレーの両方食べた")

        self.assertTrue(result["is_food_related"])
        self.assertEqual(result["highest_priority_level"], "HIGH")
        self.assertEqual(result["score"], 3)
        self.assertTrue(result["is_meat_topic"])
        self.assertIn("ステーキ", result["matched_keywords"])
        self.assertIn("カレー", result["matched_keywords"])

    def test_unrelated_text_is_not_food_related(self) -> None:
        result = self.generator.get_food_keyword_score("今日は天気がいいですね")

        self.assertFalse(result["is_food_related"])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["matched_keywords"], [])
        self.assertFalse(result["is_meat_topic"])

    def test_ng_word_blocks_detection(self) -> None:
        with mock.patch.object(self.generator, "_ng_pattern", re.compile("スパム")):
            result = self.generator.get_food_keyword_score("スパムだけどステーキ食べた")

        self.assertFalse(result["is_food_related"])
        self.assertEqual(result["score"], 0)
        self.assertTrue(result["ng_word_detected"])

    def test_is_meat_related_tweet_unaffected_by_food_expansion(self) -> None:
        # is_meat_related_tweet() はお肉のみで判定する既存メソッド。食・レストラン語彙の
        # 追加で意図せず反応が変わっていないことを回帰確認する。
        self.assertTrue(self.generator.is_meat_related_tweet("ステーキ食べた"))
        self.assertFalse(self.generator.is_meat_related_tweet("カレー食べた"))

    def test_is_food_related_tweet_covers_both_meat_and_food(self) -> None:
        self.assertTrue(self.generator.is_food_related_tweet("ステーキ食べた"))
        self.assertTrue(self.generator.is_food_related_tweet("カレー食べた"))
        self.assertFalse(self.generator.is_food_related_tweet("今日は晴れ"))


class QuoteCommentPersonaComplianceTests(TestCase):
    """引用コメント生成が絵文字ルール・口調ルールを守っているかのスモークテスト"""

    def setUp(self) -> None:
        self.generator = _make_generator()

    def test_generated_comments_follow_emoji_and_tone_rules(self) -> None:
        sample_tweets = [
            "ステーキ食べた",  # HIGH, 肉
            "焼肉最高",  # HIGH, 肉（SPECIFIC_KEYWORD_COMMENTS対象）
            "お肉美味しい",  # MEDIUM, 肉
            "カレー美味しい",  # MEDIUM, 食（肉ではない）
            "唐揚げ食べたい",  # LOW, 肉
            "お弁当買った",  # LOW, 食（肉ではない）
            "寿司食べたい",  # HIGH, 食（肉ではない）
        ]

        for text in sample_tweets:
            # ランダム選択のブレをカバーするため複数回生成する
            for _ in range(15):
                comment = self.generator.generate_quote_comment(text)
                with self.subTest(text=text, comment=comment):
                    self._assert_persona_compliant(comment, text)

    def _assert_persona_compliant(self, comment: str, source_text: str) -> None:
        # 丁寧語（です/ます）で終わっていないこと
        self.assertIsNone(
            re.search(r"(です|ます)[！!。]?\s*$", comment),
            msg=f"丁寧語が残っている: {comment!r}",
        )

        # 禁止された装飾絵文字が含まれていないこと
        for emoji in FORBIDDEN_DECORATIVE_EMOJI:
            self.assertNotIn(emoji, comment, msg=f"装飾絵文字が含まれている: {comment!r}")

        # 🐻が署名として文頭に1つだけ
        self.assertTrue(comment.startswith("🐻 "), msg=f"🐻署名が文頭にない: {comment!r}")
        self.assertEqual(comment.count("🐻"), 1, msg=f"🐻が複数ある: {comment!r}")

        # 肉系絵文字（🥩🍖）は最大1つ
        meat_emoji_count = sum(comment.count(e) for e in MEAT_EMOJI)
        self.assertLessEqual(meat_emoji_count, 1, msg=f"肉系絵文字が複数ある: {comment!r}")

        # 肉トピックでない場合は肉系絵文字が付与されないこと
        score_info = self.generator.get_food_keyword_score(source_text)
        if not score_info["is_meat_topic"]:
            self.assertEqual(meat_emoji_count, 0, msg=f"肉トピックでないのに肉系絵文字が付いている: {comment!r}")

    def test_decorate_comment_emoji_rule_directly(self) -> None:
        meat_comment = self.generator._decorate_comment("テスト", is_meat_topic=True)
        self.assertTrue(meat_comment.startswith("🐻 "))
        self.assertTrue(any(e in meat_comment for e in MEAT_EMOJI))

        non_meat_comment = self.generator._decorate_comment("テスト", is_meat_topic=False)
        self.assertTrue(non_meat_comment.startswith("🐻 "))
        self.assertFalse(any(e in non_meat_comment for e in MEAT_EMOJI))

    def test_quote_comments_file_missing_falls_back_gracefully(self) -> None:
        # data/quote_comments.tsv は非公開データのためリポジトリには存在しない。
        # 未配置でも例外にならずフォールバックで動作すること自体を確認する。
        self.assertFalse(self.generator._specific_keyword_comments == [])
        self.assertFalse(self.generator._high_priority_comments == [])
        self.assertFalse(self.generator._medium_priority_comments == [])
        self.assertFalse(self.generator._default_quote_comments == [])
