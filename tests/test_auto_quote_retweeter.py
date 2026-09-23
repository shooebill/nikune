from types import SimpleNamespace
from typing import Any, Dict
from unittest import TestCase, mock

from nikune.auto_quote_retweeter import AutoQuoteRetweeter
from nikune.jev_checker import JevChecker
from nikune.quote_safety import AVOID_KEYS, SUITABLE_KEY, VALUE_SCORE_KEY, decide, is_uncertain
from nikune.twitter_client import TwitterClient


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


class PseudoQuoteTweetTests(TestCase):
    """quote_tweet_idが使用不可(セルフサーブAPIで403)なため導入した疑似引用リツイート方式のテスト"""

    def test_pseudo_quote_tweet_dry_run_returns_mock_id(self) -> None:
        client = TwitterClient(dry_run=True)
        result = client.pseudo_quote_tweet("123", "someuser", "肉ね！")

        self.assertEqual(result, "mock_tweet_id")

    def test_pseudo_quote_tweet_without_author_username_fails_gracefully(self) -> None:
        client = TwitterClient(dry_run=True)
        result = client.pseudo_quote_tweet("123", None, "肉ね！")

        self.assertIsNone(result)


class FoodSearchQueryTests(TestCase):
    """フォロー関係に依存しない検索API探索（ハイブリッド方式）のクエリ組み立てテスト"""

    def test_build_food_search_query_includes_keywords_and_filters(self) -> None:
        retweeter = _make_retweeter()
        query = retweeter._build_food_search_query()

        self.assertIn("肉", query)
        self.assertIn("寿司", query)
        self.assertIn("OR", query)
        self.assertIn("-is:retweet", query)
        self.assertIn("lang:ja", query)

    def test_fetch_search_candidates_returns_empty_list_on_failure(self) -> None:
        retweeter = _make_retweeter()
        with mock.patch.object(retweeter.twitter_client, "search_recent_food_tweets", side_effect=RuntimeError("boom")):
            candidates = retweeter._fetch_search_candidates()

        self.assertEqual(candidates, [])


def _jev_response(nouls: Dict[str, float], value_score: float = 2.0) -> SimpleNamespace:
    return SimpleNamespace(
        model="jev-1.13.0",
        nouls={key: SimpleNamespace(noul=value) for key, value in nouls.items()},
        scores={VALUE_SCORE_KEY: SimpleNamespace(score=value_score)},
    )


SAFE_NOULS: Dict[str, float] = {SUITABLE_KEY: 0.95, **{key: 0.03 for key in AVOID_KEYS}}

FOOD_TWEET = SimpleNamespace(
    id="jev_candidate_1",
    text="テストのカレーを食べた",
    author_id="jev_user_1",
    author_username="jev_user_1",
    created_at="2026-09-23T09:00:00.000Z",
)


class JevQuoteSafetyTests(TestCase):
    """キーワード一致を通過した候補に対するJev二次フィルタの配線テスト（Jevはモック）"""

    def _run(self, client: mock.MagicMock) -> tuple[AutoQuoteRetweeter, Dict[str, Any], mock.MagicMock]:
        retweeter = AutoQuoteRetweeter(
            db_manager=mock.MagicMock(), dry_run=True, jev_checker=JevChecker(api_key="fake", client=client)
        )
        with (
            mock.patch.object(retweeter, "_get_mock_timeline", return_value=[FOOD_TWEET]),
            mock.patch.object(
                retweeter.content_generator, "generate_quote_comment", return_value="テスト"
            ) as generate_comment,
        ):
            results = retweeter.check_and_quote_tweets()
        return retweeter, results, generate_comment

    def test_safe_candidate_proceeds_to_quote(self) -> None:
        client = mock.MagicMock()
        client.system_one.return_value = _jev_response(SAFE_NOULS)

        retweeter, results, generate_comment = self._run(client)

        self.assertTrue(results["success"])
        client.system_one.assert_called_once()
        generate_comment.assert_called_once()
        self.assertEqual(results["skipped_by_jev"], 0)
        self.assertIn(FOOD_TWEET.id, retweeter.processed_tweets)
        # 候補本文がStateとして渡っている
        state = client.system_one.call_args.kwargs["state"]
        self.assertEqual(state["candidate_post"]["text"], FOOD_TWEET.text)

    def test_high_avoid_noul_skips_candidate(self) -> None:
        client = mock.MagicMock()
        client.system_one.return_value = _jev_response({**SAFE_NOULS, "tragedy_context": 0.9})

        retweeter, results, generate_comment = self._run(client)

        self.assertTrue(results["success"])
        generate_comment.assert_not_called()
        self.assertEqual(results["skipped_by_jev"], 1)
        # 判定済みの不適切候補は処理済みにして再問い合わせしない
        self.assertIn(FOOD_TWEET.id, retweeter.processed_tweets)

    def test_low_suitable_noul_skips_candidate(self) -> None:
        client = mock.MagicMock()
        client.system_one.return_value = _jev_response({**SAFE_NOULS, SUITABLE_KEY: 0.1})

        _, results, generate_comment = self._run(client)

        generate_comment.assert_not_called()
        self.assertEqual(results["skipped_by_jev"], 1)

    def test_uncertain_noul_skips_candidate(self) -> None:
        # しきい値だけなら通る値でも、0.5付近（あいまい帯）なら引用しない
        with mock.patch("nikune.quote_safety.AVOID_THRESHOLD", 0.9):
            client = mock.MagicMock()
            client.system_one.return_value = _jev_response({**SAFE_NOULS, "promotion_context": 0.5})
            _, results, generate_comment = self._run(client)

        generate_comment.assert_not_called()
        self.assertEqual(results["skipped_by_jev"], 1)

    def test_typesafe_failure_skips_without_exception_and_is_not_marked_processed(self) -> None:
        client = mock.MagicMock()
        client.system_one.side_effect = RuntimeError("service down")

        retweeter, results, generate_comment = self._run(client)

        self.assertTrue(results["success"])
        self.assertEqual(results["errors"], [])
        generate_comment.assert_not_called()
        self.assertEqual(results["jev_unavailable"], 1)
        self.assertEqual(results["quote_posted"], 0)
        # 一時的な障害で候補を失わないよう処理済みにはしない
        self.assertNotIn(FOOD_TWEET.id, retweeter.processed_tweets)

    def test_missing_key_behaves_as_before(self) -> None:
        retweeter = AutoQuoteRetweeter(db_manager=mock.MagicMock(), dry_run=True)
        self.assertFalse(retweeter.jev_checker.enabled)

        with (
            mock.patch("nikune.jev_checker.TypeSafeClient") as client_cls,
            mock.patch.object(retweeter, "_get_mock_timeline", return_value=[FOOD_TWEET]),
        ):
            results = retweeter.check_and_quote_tweets()

        client_cls.assert_not_called()
        self.assertTrue(results["success"])
        self.assertEqual(results["food_related_found"], 1)
        self.assertEqual(results["skipped_by_jev"], 0)
        self.assertEqual(results["jev_unavailable"], 0)
        self.assertIn(FOOD_TWEET.id, retweeter.processed_tweets)


class QuoteSafetyRuleTests(TestCase):
    def test_uncertain_band(self) -> None:
        self.assertTrue(is_uncertain(0.5))
        self.assertTrue(is_uncertain(0.6))
        self.assertFalse(is_uncertain(0.9))
        self.assertFalse(is_uncertain(0.05))

    def test_decide_accepts_clear_safe_values(self) -> None:
        self.assertEqual(decide(SAFE_NOULS), [])
