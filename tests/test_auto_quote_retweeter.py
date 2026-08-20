from types import SimpleNamespace
from unittest import TestCase, mock

from nikune.auto_quote_retweeter import AutoQuoteRetweeter


def _make_retweeter() -> AutoQuoteRetweeter:
    # DB接続（Redis/SQLite）・Twitter API認証はdry_run=Trueで不要になる
    return AutoQuoteRetweeter(db_manager=mock.MagicMock(), dry_run=True)


class FoodKeywordWiringTests(TestCase):
    """get_food_keyword_score()への切り替えが正しく配線されているかの確認"""

    def test_check_and_quote_tweets_detects_food_related_mock_timeline(self) -> None:
        retweeter = _make_retweeter()
        results = retweeter.check_and_quote_tweets()

        self.assertTrue(results["success"])
        self.assertEqual(results["checked_tweets"], 7)
        # モックタイムラインの1件目（肉+ランチ）がMEDIUM優先度でヒットし、
        # そこでループがbreakする既存仕様（優先度が低い場合は1件で終了）。
        # 6・7件目（寿司・カレー）は食・レストラン拡張の網羅性確認用データで、
        # 1件目でbreakするため実際には評価されない。
        self.assertEqual(results["food_related_found"], 1)

    def test_low_priority_food_keyword_score(self) -> None:
        retweeter = _make_retweeter()
        score_info = retweeter.content_generator.get_food_keyword_score("お弁当買った")

        self.assertTrue(score_info["is_food_related"])
        self.assertEqual(score_info["score"], 1)  # LOW

    def test_high_priority_food_keyword_matches_meat_priority_threshold(self) -> None:
        retweeter = _make_retweeter()
        # 寿司（食のHIGH=3）がお肉のHIGHと同じスコアのため、高優先度レート制限の
        # 対象閾値（high_priority_score）と一致することを確認する。
        score_info = retweeter.content_generator.get_food_keyword_score("寿司食べたい")

        self.assertEqual(score_info["score"], 3)
        self.assertEqual(score_info["score"], retweeter.high_priority_score)


class DuplicatePreventionTests(TestCase):
    """マッチ対象拡大後もレート制限・重複防止ロジックが従来通り機能するかの回帰確認"""

    def test_duplicate_tweet_is_skipped_on_second_pass(self) -> None:
        retweeter = _make_retweeter()

        first = retweeter.check_and_quote_tweets()
        second = retweeter.check_and_quote_tweets()

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        # 1回目で処理済みとしてマークされたツイートは2回目でスキップされる
        self.assertGreaterEqual(second.get("skipped_already_processed", 0), 1)

    def test_dry_run_never_actually_posts(self) -> None:
        retweeter = _make_retweeter()
        results = retweeter.check_and_quote_tweets()

        self.assertEqual(results["quote_posted"], 0)


class MockTimelineFoodExpansionTests(TestCase):
    """食・レストラン系のモックツイートでも検出できることの確認（Day5テスト整備）"""

    def test_mock_timeline_with_restaurant_tweet_is_detected(self) -> None:
        retweeter = _make_retweeter()

        restaurant_tweet = SimpleNamespace(
            id="mock_restaurant_1",
            text="今日はカレーを食べに行った、美味しかった",
            author_id="mock_user_restaurant",
            created_at="2026-08-20T09:00:00.000Z",
        )

        with mock.patch.object(retweeter, "_get_mock_timeline", return_value=[restaurant_tweet]):
            results = retweeter.check_and_quote_tweets()

        self.assertTrue(results["success"])
        self.assertEqual(results["food_related_found"], 1)

    def test_mock_timeline_with_unrelated_tweet_is_not_detected(self) -> None:
        retweeter = _make_retweeter()

        unrelated_tweet = SimpleNamespace(
            id="mock_unrelated_1",
            text="今日は天気がいいですね",
            author_id="mock_user_unrelated",
            created_at="2026-08-20T09:00:00.000Z",
        )

        with mock.patch.object(retweeter, "_get_mock_timeline", return_value=[unrelated_tweet]):
            results = retweeter.check_and_quote_tweets()

        self.assertTrue(results["success"])
        self.assertEqual(results["food_related_found"], 0)
