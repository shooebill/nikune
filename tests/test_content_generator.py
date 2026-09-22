import re
from unittest import TestCase, mock

from nikune.content_generator import ContentGenerator, GeneratedTweetContent

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

    def test_lowercase_bbq_is_still_recognized_as_meat_topic(self) -> None:
        # バグ回帰テスト: 食キーワードのマッチはre.IGNORECASEで行われるため、
        # マッチした元テキストの大文字小文字のままの部分文字列（例: "bbq"）が
        # MEAT_KEYWORDS側の表記（"BBQ"）とcase-sensitiveに比較されると、
        # 小文字表記のツイートがis_meat_topic=Falseになってしまっていた。
        result = self.generator.get_food_keyword_score("bbq最高だった")

        self.assertTrue(result["is_food_related"])
        self.assertIn("bbq", result["matched_keywords"])
        self.assertTrue(result["is_meat_topic"])

    def test_uppercase_bbq_is_recognized_as_meat_topic(self) -> None:
        result = self.generator.get_food_keyword_score("BBQ最高だった")

        self.assertTrue(result["is_food_related"])
        self.assertTrue(result["is_meat_topic"])


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


class TweetSignatureEnforcementTests(TestCase):
    """通常投稿の絵文字ルール（署名🐻の文頭保証・装飾絵文字の警告）"""

    def setUp(self) -> None:
        self.generator = _make_generator()

    def test_signature_is_prepended_when_missing(self) -> None:
        self.assertEqual(self.generator._apply_signature("テスト"), "🐻 テスト")

    def test_signature_is_not_duplicated_when_present(self) -> None:
        self.assertEqual(self.generator._apply_signature("🐻 テスト"), "🐻 テスト")

    def test_signature_is_prepended_before_other_leading_emoji(self) -> None:
        self.assertEqual(self.generator._apply_signature("🥩 テスト"), "🐻 🥩 テスト")

    def test_decorative_emoji_logs_warning_but_is_not_removed(self) -> None:
        with self.assertLogs("nikune.content_generator", level="WARNING") as captured:
            result = self.generator._apply_signature("🐻 テスト ✨")
        self.assertEqual(result, "🐻 テスト ✨")
        self.assertTrue(any("装飾絵文字" in message for message in captured.output))

    def test_clean_template_logs_no_warning(self) -> None:
        with self.assertNoLogs("nikune.content_generator", level="WARNING"):
            self.generator._apply_signature("🐻 テスト 🥩")

    def test_process_template_applies_signature(self) -> None:
        processed = self.generator._process_template({"id": "1", "template": "テスト"})
        self.assertEqual(processed, "🐻 テスト")

    def test_prohibited_list_covers_persona_forbidden_emoji(self) -> None:
        # テスト側の禁止リストのうち、コード側に無いものが増えていないこと（👑はペルソナ文書外のため除外）
        missing = [
            e for e in FORBIDDEN_DECORATIVE_EMOJI if e != "👑" and e not in self.generator.PROHIBITED_DECORATIVE_EMOJIS
        ]
        self.assertEqual(missing, [])


class TweetContentGenerationCooldownTests(TestCase):
    """
    バグ回帰テスト: generate_tweet_content()は投稿成功前にテンプレートのクールダウンを
    消費してはいけない（Redisへの書き込みは呼び出し元がrecord_tweet_usage()で行う）
    """

    def setUp(self) -> None:
        self.db_manager = mock.MagicMock()
        self.db_manager.get_available_template.return_value = {"id": "1", "template": "テスト"}
        self.generator = ContentGenerator(db_manager=self.db_manager)

    def test_generate_tweet_content_has_no_side_effect(self) -> None:
        generated = self.generator.generate_tweet_content()

        self.assertIsInstance(generated, GeneratedTweetContent)
        assert generated is not None
        self.assertEqual(generated.template_id, 1)
        self.assertEqual(generated.text, "🐻 テスト")
        # 生成しただけではRedisへの使用履歴記録（クールダウン消費）が起きないこと
        self.db_manager.record_tweet_usage.assert_not_called()

    def test_record_tweet_usage_forwards_to_db_manager(self) -> None:
        generated = self.generator.generate_tweet_content()
        assert generated is not None

        # 投稿成功を模した後、明示的にrecord_tweet_usage()を呼んだ場合のみ記録される
        self.generator.record_tweet_usage(generated.template_id, generated.text)

        self.db_manager.record_tweet_usage.assert_called_once_with(generated.template_id, generated.text)

    def test_generate_tweet_content_returns_none_when_no_template_available(self) -> None:
        self.db_manager.get_available_template.return_value = None

        generated = self.generator.generate_tweet_content()

        self.assertIsNone(generated)
        self.db_manager.record_tweet_usage.assert_not_called()
