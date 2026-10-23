from types import SimpleNamespace
from typing import Any, Dict
from unittest import TestCase, mock

from nikune.auto_quote_retweeter import AutoQuoteRetweeter
from nikune.jev_checker import JevChecker
from nikune.meat_focus import MEAT_MAIN_KEY, MeatFocusVerdict
from nikune.photo_checker import CommentVerdict, PhotoChecker, PhotoVerdict
from nikune.quote_safety import AVOID_KEYS, SUITABLE_KEY, VALUE_SCORE_KEY, decide, is_uncertain
from nikune.twitter_client import TwitterClient


def _make_db_mock() -> mock.MagicMock:
    # 引用RT履歴は空（過去に引用したツイートなし）として扱う
    db = mock.MagicMock()
    db.has_quoted.return_value = False
    db.get_quotes_since.return_value = []
    db.get_quoted_authors_since.return_value = set()
    return db


def _make_retweeter() -> AutoQuoteRetweeter:
    # DB接続（Redis/SQLite）・Twitter API認証はdry_run=Trueで不要になる
    return AutoQuoteRetweeter(db_manager=_make_db_mock(), dry_run=True)


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
    # 「肉が主役か」の問い合わせ（nikune/meat_focus.py）にも同じモックが答えるので、肉が主役として返しておく
    nouls = {MEAT_MAIN_KEY: 0.9, **nouls}
    return SimpleNamespace(
        model="jev-1.13.0",
        nouls={key: SimpleNamespace(noul=value) for key, value in nouls.items()},
        scores={VALUE_SCORE_KEY: SimpleNamespace(score=value_score)},
    )


SAFE_NOULS: Dict[str, float] = {SUITABLE_KEY: 0.95, **{key: 0.03 for key in AVOID_KEYS}}

FOOD_TWEET = SimpleNamespace(
    id="jev_candidate_1",
    text="テストの牛肉を食べた",
    author_id="jev_user_1",
    author_username="jev_user_1",
    created_at="2026-09-23T09:00:00.000Z",
)


class JevQuoteSafetyTests(TestCase):
    """キーワード一致を通過した候補に対するJev二次フィルタの配線テスト（Jevはモック）"""

    def _run(self, client: mock.MagicMock) -> tuple[AutoQuoteRetweeter, Dict[str, Any], mock.MagicMock]:
        retweeter = AutoQuoteRetweeter(
            db_manager=_make_db_mock(), dry_run=True, jev_checker=JevChecker(api_key="fake", client=client)
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
        # 1回目は「肉が主役か」、2回目が安全判定
        self.assertEqual(client.system_one.call_count, 2)
        self.assertIn(MEAT_MAIN_KEY, client.system_one.call_args_list[0].kwargs["questions"])
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
        retweeter = AutoQuoteRetweeter(db_manager=_make_db_mock(), dry_run=True)
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


def _food_tweet(tweet_id: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(id=tweet_id, text=text, author_id="u", author_username="u", created_at="")


def _run_live(
    db: mock.MagicMock, tweets: list[SimpleNamespace]
) -> tuple[AutoQuoteRetweeter, Dict[str, Any], mock.MagicMock]:
    retweeter = AutoQuoteRetweeter(db_manager=db, dry_run=True)
    retweeter.dry_run = False  # 投稿はモックに差し替えて本番経路を通す
    with (
        mock.patch.object(retweeter, "_fetch_timeline_with_retry", return_value=tweets),
        mock.patch.object(retweeter, "_fetch_search_candidates", return_value=[]),
        mock.patch.object(retweeter.twitter_client, "pseudo_quote_tweet", return_value="q1") as post,
    ):
        results = retweeter.check_and_quote_tweets()
    return retweeter, results, post


class CrossRunRateLimitTests(TestCase):
    """cronで毎回別プロセスとして起動しても、上限を超えて・同じツイートを引用しないことの確認
    （2026-09-27 12:30、HIGH優先度の候補が続いて1回の実行で3件投稿した不具合の回帰テスト）"""

    def test_consecutive_high_priority_candidates_post_only_once(self) -> None:
        db = _make_db_mock()
        tweets = [_food_tweet("t1", "焼肉たべた"), _food_tweet("t2", "ステーキたべた"), _food_tweet("t3", "牛丼")]

        _, results, post = _run_live(db, tweets)

        self.assertEqual(results["quote_posted"], 1)
        post.assert_called_once()
        db.record_quote.assert_called_once()
        self.assertEqual(db.record_quote.call_args.args[:2], ("t1", "q1"))

    def test_tweet_quoted_in_previous_run_is_skipped(self) -> None:
        db = _make_db_mock()
        db.has_quoted.side_effect = lambda tweet_id: tweet_id == "t1"
        tweets = [_food_tweet("t1", "焼肉たべた"), _food_tweet("t2", "ステーキたべた")]

        _, results, post = _run_live(db, tweets)

        self.assertEqual(results["quote_posted"], 1)
        self.assertEqual(post.call_args.args[0], "t2")

    def test_recent_quote_in_previous_run_blocks_this_run(self) -> None:
        from datetime import datetime, timedelta

        db = _make_db_mock()
        db.get_quotes_since.return_value = [{"quoted_at": datetime.now() - timedelta(minutes=10), "priority_score": 3}]

        retweeter, results, post = _run_live(db, [_food_tweet("t1", "焼肉たべた")])

        self.assertEqual(results["skipped_rate_limit"], 1)
        post.assert_not_called()
        self.assertIsNotNone(retweeter.last_quote_time)


class SameAuthorCooldownTests(TestCase):
    """同じアカウントを続けて引用しないことの確認
    （9/23〜10/9の引用17件のうち13件が3アカウントに偏り、連日や同じ日に同じ相手を引用していた）"""

    def test_author_quoted_recently_is_skipped(self) -> None:
        db = _make_db_mock()
        db.get_quoted_authors_since.return_value = {"meat_lover"}
        tweets = [
            SimpleNamespace(id="t1", text="焼肉たべた", author_id="a", author_username="Meat_Lover", created_at=""),
            SimpleNamespace(id="t2", text="ステーキたべた", author_id="b", author_username="other", created_at=""),
        ]

        _, results, post = _run_live(db, tweets)

        # アカウント名は大文字・小文字を区別せずに比べる
        self.assertEqual(results["skipped_recent_author"], 1)
        self.assertEqual(post.call_args.args[0], "t2")

    def test_only_recent_author_means_no_quote(self) -> None:
        db = _make_db_mock()
        db.get_quoted_authors_since.return_value = {"u"}

        _, results, post = _run_live(db, [_food_tweet("t1", "焼肉たべた")])

        self.assertEqual(results["quote_posted"], 0)
        post.assert_not_called()

    def test_cooldown_window_and_author_are_recorded(self) -> None:
        from datetime import datetime, timedelta

        db = _make_db_mock()

        retweeter, _, _ = _run_live(db, [_food_tweet("t1", "焼肉たべた")])

        since = db.get_quoted_authors_since.call_args.args[0]
        self.assertAlmostEqual(
            (datetime.now() - since).total_seconds(), retweeter.same_author_cooldown.total_seconds(), delta=60
        )
        self.assertEqual(retweeter.same_author_cooldown, timedelta(days=3))
        self.assertEqual(db.record_quote.call_args.args[4], "u")

    def test_same_author_is_not_quoted_twice_in_one_run(self) -> None:
        # HIGH優先度の候補は1回の実行で続けて引用しうる（9/27に同じ相手を同じ回で2件引用した）
        db = _make_db_mock()
        tweets = [
            SimpleNamespace(id="t1", text="焼肉たべた", author_id="a", author_username="same", created_at=""),
            SimpleNamespace(id="t2", text="ステーキたべた", author_id="a", author_username="same", created_at=""),
        ]
        retweeter = AutoQuoteRetweeter(db_manager=db, dry_run=True)
        retweeter.dry_run = False
        # レート制限ではなく相手で止まることを見るため、レート制限は外す
        with (
            mock.patch.object(retweeter, "_can_quote_now", return_value=True),
            mock.patch.object(retweeter, "_can_quote_high_priority", return_value=True),
            mock.patch.object(retweeter, "_fetch_timeline_with_retry", return_value=tweets),
            mock.patch.object(retweeter, "_fetch_search_candidates", return_value=[]),
            mock.patch.object(retweeter.twitter_client, "pseudo_quote_tweet", return_value="q1") as post,
        ):
            results = retweeter.check_and_quote_tweets()

        post.assert_called_once()
        self.assertEqual(results["skipped_recent_author"], 1)


def _tweet_posted(tweet_id: str, text: str, hours_ago: float) -> SimpleNamespace:
    from datetime import datetime, timedelta, timezone

    posted_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return SimpleNamespace(id=tweet_id, text=text, author_id="u", author_username="u", created_at=posted_at)


class TweetAgeFilterTests(TestCase):
    """古いツイートやリツイートを引用しないことの確認
    （前の晩22〜23時台の投稿に、翌朝8:30の回が朝のあいさつ付きで引用していた不具合の回帰テスト）"""

    def test_old_tweet_is_skipped_and_fresh_one_is_quoted(self) -> None:
        db = _make_db_mock()
        tweets = [_tweet_posted("old", "焼肉たべた", hours_ago=9), _tweet_posted("fresh", "牛丼", hours_ago=1)]

        _, results, post = _run_live(db, tweets)

        self.assertEqual(results["skipped_too_old"], 1)
        self.assertEqual(results["quote_posted"], 1)
        self.assertEqual(post.call_args.args[0], "fresh")

    def test_only_old_tweets_posts_nothing(self) -> None:
        db = _make_db_mock()

        _, results, post = _run_live(db, [_tweet_posted("old", "焼肉たべた", hours_ago=3.5)])

        self.assertTrue(results["success"])
        self.assertEqual(results["quote_posted"], 0)
        post.assert_not_called()

    def test_retweet_is_skipped(self) -> None:
        db = _make_db_mock()

        _, results, post = _run_live(db, [_tweet_posted("rt", "RT @someone: 牛スジでカレーを作った", hours_ago=0.5)])

        self.assertEqual(results["skipped_retweet"], 1)
        post.assert_not_called()

    def test_tweet_without_known_post_time_is_not_skipped(self) -> None:
        db = _make_db_mock()

        _, results, post = _run_live(db, [_food_tweet("t1", "焼肉たべた")])

        self.assertEqual(results["skipped_too_old"], 0)
        post.assert_called_once()

    def test_time_phrase_follows_the_tweet_post_time(self) -> None:
        db = _make_db_mock()
        tweet = _tweet_posted("t1", "牛丼", hours_ago=1)
        retweeter = AutoQuoteRetweeter(db_manager=db, dry_run=True)
        retweeter.dry_run = False
        with (
            mock.patch.object(retweeter, "_fetch_timeline_with_retry", return_value=[tweet]),
            mock.patch.object(retweeter, "_fetch_search_candidates", return_value=[]),
            mock.patch.object(retweeter.twitter_client, "pseudo_quote_tweet", return_value="q1"),
            mock.patch.object(retweeter.content_generator, "generate_quote_comment", return_value="c") as generate,
        ):
            retweeter.check_and_quote_tweets()

        self.assertEqual(generate.call_args.args, ("牛丼", tweet.created_at, []))


class MeatFirstSelectionTests(TestCase):
    """肉の話題を優先し、汎用の文言しか付けられない食べ物は引用しないことの確認
    （9/28〜10/9の引用10件のうち、肉のキーワードで拾えたのが1件だけだったことへの対応）"""

    def _retweeter_with_dedicated_comment(self, keyword: str) -> AutoQuoteRetweeter:
        retweeter = AutoQuoteRetweeter(db_manager=_make_db_mock(), dry_run=True)
        retweeter.dry_run = False
        retweeter.content_generator._specific_keyword_comments = [(keyword, ["テスト用の専用コメント"])]
        return retweeter

    def _run(
        self, retweeter: AutoQuoteRetweeter, timeline: list[SimpleNamespace], search: list[SimpleNamespace]
    ) -> Any:
        with (
            mock.patch.object(retweeter, "_fetch_timeline_with_retry", return_value=timeline),
            mock.patch.object(retweeter, "_fetch_search_candidates", return_value=search),
            mock.patch.object(retweeter.twitter_client, "pseudo_quote_tweet", return_value="q1") as post,
        ):
            results = retweeter.check_and_quote_tweets()
        return results, post

    def test_meat_tweet_is_quoted_even_when_other_food_comes_first(self) -> None:
        retweeter = self._retweeter_with_dedicated_comment("寿司")
        timeline = [
            _food_tweet("sushi", "寿司たべた"),
            _food_tweet("lunch", "今日のランチ"),
            _food_tweet("meat", "牛肉"),
        ]

        results, post = self._run(retweeter, timeline, [])

        self.assertEqual(results["quote_posted"], 1)
        self.assertEqual(post.call_args.args[0], "meat")

    def test_food_with_dedicated_comment_is_quoted_when_no_meat(self) -> None:
        retweeter = self._retweeter_with_dedicated_comment("寿司")
        timeline = [_food_tweet("lunch", "今日のランチ"), _food_tweet("sushi", "寿司たべた")]

        results, post = self._run(retweeter, timeline, [])

        self.assertEqual(post.call_args.args[0], "sushi")
        self.assertEqual(post.call_args.args[2].count("テスト用の専用コメント"), 1)

    def test_food_without_dedicated_comment_is_not_quoted(self) -> None:
        retweeter = self._retweeter_with_dedicated_comment("寿司")
        timeline = [_food_tweet("lunch", "今日のランチ"), _food_tweet("curry", "カレーたべた")]

        results, post = self._run(retweeter, timeline, [])

        self.assertTrue(results["success"])
        self.assertEqual(results["skipped_no_fitting_comment"], 2)
        post.assert_not_called()

    def test_timeline_comes_before_search_within_the_same_rank(self) -> None:
        retweeter = self._retweeter_with_dedicated_comment("寿司")
        search = [_food_tweet("search_meat", "焼肉たべた")]
        timeline = [_food_tweet("sushi", "寿司たべた"), _food_tweet("timeline_meat", "牛肉")]

        _, post = self._run(retweeter, timeline, search)

        self.assertEqual(post.call_args.args[0], "timeline_meat")

    def test_cut_names_without_the_meat_character_count_as_meat(self) -> None:
        retweeter = _make_retweeter()
        for text in ["牛スジでカレーを作った", "カレーの具に豚タン"]:
            with self.subTest(text=text):
                score_info = retweeter.content_generator.get_food_keyword_score(text)
                self.assertTrue(score_info["is_meat_topic"])


def _photo_tweet(tweet_id: str, text: str) -> SimpleNamespace:
    photo_url = f"https://example.com/{tweet_id}.jpg"
    return SimpleNamespace(
        id=tweet_id, text=text, author_id="u", author_username="u", created_at="", photo_urls=[photo_url]
    )


class PhotoCheckTests(TestCase):
    """写真付きの候補は写真も見て、肉が写っている投稿を最優先にすることの確認"""

    def _run(
        self, verdicts: Dict[str, Any], timeline: list[SimpleNamespace], max_per_run: int = 5
    ) -> tuple[Dict[str, Any], mock.MagicMock, mock.MagicMock]:
        photo_checker = mock.MagicMock(spec=PhotoChecker)
        photo_checker.enabled = True
        photo_checker.check.side_effect = lambda url, dishes, text: verdicts.get(
            url.rsplit("/", 1)[-1].removesuffix(".jpg")
        )
        photo_checker.comment_fits.return_value = CommentVerdict(fits=True, reason="ok")
        retweeter = AutoQuoteRetweeter(db_manager=_make_db_mock(), dry_run=True, photo_checker=photo_checker)
        retweeter.dry_run = False
        retweeter.content_generator._specific_keyword_comments = [("寿司", ["テスト用の専用コメント"])]
        with (
            mock.patch.object(retweeter, "_fetch_timeline_with_retry", return_value=timeline),
            mock.patch.object(retweeter, "_fetch_search_candidates", return_value=[]),
            mock.patch.object(retweeter.twitter_client, "pseudo_quote_tweet", return_value="q1") as post,
            mock.patch("nikune.auto_quote_retweeter.PHOTO_CHECK_MAX_PER_RUN", max_per_run),
        ):
            results = retweeter.check_and_quote_tweets()
        return results, post, photo_checker

    def test_meat_in_photo_is_quoted_even_when_the_text_has_no_food_word(self) -> None:
        verdicts = {"shop": PhotoVerdict(is_food=True, shows_meat=True, dishes=[])}
        timeline = [_food_tweet("text_meat", "牛肉"), _photo_tweet("shop", "三軒茶屋のお店。")]

        results, post, _ = self._run(verdicts, timeline)

        self.assertEqual(results["photo_checked"], 1)
        self.assertEqual(post.call_args.args[0], "shop")

    def test_dish_in_photo_selects_its_dedicated_comment(self) -> None:
        verdicts = {"date_only": PhotoVerdict(is_food=True, shows_meat=False, dishes=["寿司"])}

        _, post, _ = self._run(verdicts, [_photo_tweet("date_only", "2026年10月8日")])

        self.assertEqual(post.call_args.args[0], "date_only")
        self.assertIn("テスト用の専用コメント", post.call_args.args[2])

    def test_non_food_photo_does_not_make_a_tweet_quotable(self) -> None:
        verdicts = {"cat": PhotoVerdict(is_food=False, shows_meat=False, dishes=[])}

        _, post, _ = self._run(verdicts, [_photo_tweet("cat", "かわいい")])

        post.assert_not_called()

    def test_failed_photo_check_falls_back_to_text_rules(self) -> None:
        results, post, _ = self._run({}, [_photo_tweet("meat", "焼肉たべた")])

        self.assertEqual(results["photo_unavailable"], 1)
        self.assertEqual(post.call_args.args[0], "meat")

    def test_photo_checks_are_capped_per_run(self) -> None:
        timeline = [_photo_tweet(f"t{i}", "かわいい") for i in range(4)]

        _, _, photo_checker = self._run({}, timeline, max_per_run=2)

        self.assertEqual(photo_checker.check.call_count, 2)

    def test_old_tweets_and_tweets_without_photos_are_not_sent(self) -> None:
        old = _tweet_posted("old", "焼肉たべた", hours_ago=9)
        old.photo_urls = ["https://example.com/old.jpg"]

        _, _, photo_checker = self._run({}, [old, _food_tweet("no_photo", "牛肉")])

        photo_checker.check.assert_not_called()

    def test_disabled_checker_is_never_called(self) -> None:
        retweeter = AutoQuoteRetweeter(db_manager=_make_db_mock(), dry_run=True)

        self.assertFalse(retweeter.photo_checker.enabled)
        self.assertEqual(retweeter._check_photos([_photo_tweet("t1", "焼肉")], set(), {}), {})


class CommentCheckTests(TestCase):
    """選んだセリフが投稿の内容と食い違うときは、選び直すか引用を見送ることの確認"""

    DEDICATED = "テスト用の専用コメント"

    def _run(
        self, fits: list[Any], timeline: list[SimpleNamespace], max_checks: int = 6
    ) -> tuple[Dict[str, Any], mock.MagicMock, mock.MagicMock]:
        photo_checker = mock.MagicMock(spec=PhotoChecker)
        photo_checker.enabled = True
        photo_checker.check.return_value = None
        photo_checker.comment_fits.side_effect = [
            None if fit is None else CommentVerdict(fits=fit, reason="test") for fit in fits
        ]
        retweeter = AutoQuoteRetweeter(db_manager=_make_db_mock(), dry_run=True, photo_checker=photo_checker)
        retweeter.dry_run = False
        retweeter.content_generator._specific_keyword_comments = [
            ("焼き鳥", [self.DEDICATED]),
            ("寿司", [self.DEDICATED]),
        ]
        with (
            mock.patch.object(retweeter, "_fetch_timeline_with_retry", return_value=timeline),
            mock.patch.object(retweeter, "_fetch_search_candidates", return_value=[]),
            mock.patch.object(retweeter.twitter_client, "pseudo_quote_tweet", return_value="q1") as post,
            mock.patch("nikune.auto_quote_retweeter.COMMENT_CHECK_MAX_PER_RUN", max_checks),
        ):
            results = retweeter.check_and_quote_tweets()
        return results, post, photo_checker

    def test_fitting_comment_is_posted_as_selected(self) -> None:
        tweet = _photo_tweet("t1", "焼き鳥たべた")

        results, post, photo_checker = self._run([True], [tweet])

        self.assertIn(self.DEDICATED, post.call_args.args[2])
        self.assertEqual(results["comment_checks"], 1)
        comment, text, photo_url = photo_checker.comment_fits.call_args.args
        self.assertIn(self.DEDICATED, comment)
        self.assertEqual(text, "焼き鳥たべた")
        self.assertEqual(photo_url, "https://example.com/t1.jpg")

    def test_mismatched_dedicated_comment_is_replaced_with_a_generic_one(self) -> None:
        results, post, _ = self._run([False, True], [_food_tweet("t1", "豚肉なのに焼き鳥と呼ぶ")])

        self.assertEqual(results["quote_posted"], 1)
        self.assertNotIn(self.DEDICATED, post.call_args.args[2])
        self.assertEqual(results["comment_checks"], 2)

    def test_tweet_is_skipped_when_no_comment_fits(self) -> None:
        results, post, _ = self._run([False, False], [_food_tweet("t1", "豚肉なのに焼き鳥と呼ぶ")])

        post.assert_not_called()
        self.assertEqual(results["skipped_comment_mismatch"], 1)

    def test_non_meat_tweet_is_skipped_without_trying_a_generic_comment(self) -> None:
        results, post, _ = self._run([False], [_food_tweet("t1", "寿司ではなかった")])

        post.assert_not_called()
        self.assertEqual(results["comment_checks"], 1)
        self.assertEqual(results["skipped_comment_mismatch"], 1)

    def test_next_candidate_is_tried_after_a_skip(self) -> None:
        timeline = [_food_tweet("t1", "寿司ではなかった"), _food_tweet("t2", "寿司たべた")]

        results, post, _ = self._run([False, True], timeline)

        self.assertEqual(post.call_args.args[0], "t2")
        self.assertEqual(results["quote_posted"], 1)

    def test_nothing_is_quoted_when_the_check_is_unavailable(self) -> None:
        timeline = [_food_tweet("t1", "焼き鳥たべた"), _food_tweet("t2", "寿司たべた")]

        results, post, photo_checker = self._run([None], timeline)

        post.assert_not_called()
        self.assertEqual(results["comment_check_unavailable"], 1)
        self.assertEqual(results["skipped_comment_mismatch"], 0)
        self.assertEqual(photo_checker.comment_fits.call_count, 1)

    def test_run_stops_when_the_check_limit_is_reached(self) -> None:
        timeline = [_food_tweet("t1", "寿司ではなかった"), _food_tweet("t2", "寿司たべた")]

        results, post, photo_checker = self._run([False], timeline, max_checks=1)

        post.assert_not_called()
        self.assertEqual(photo_checker.comment_fits.call_count, 1)

    def test_no_check_is_made_without_a_key(self) -> None:
        retweeter = AutoQuoteRetweeter(db_manager=_make_db_mock(), dry_run=True)
        results: Dict[str, Any] = {"comment_checks": 0, "comment_check_unavailable": 0}
        score_info = retweeter.content_generator.get_food_keyword_score("焼肉たべた")

        comment = retweeter._fitting_comment(_food_tweet("t1", "焼肉たべた"), None, [], score_info, results)

        self.assertTrue(comment)
        self.assertEqual(results["comment_checks"], 0)


class MeatFocusTests(TestCase):
    """肉が入っていても主役ではない投稿を、肉の話題として最優先にしないことの確認
    （2026-10-20、牛肉の乗ったそうめんのレシピを、写真に肉が写っていて本文に「焼肉のタレ」があるため
    肉の話題として引用した）"""

    def _run(
        self,
        meat_main: Dict[str, Any],
        timeline: list[SimpleNamespace],
        photo_verdicts: Dict[str, PhotoVerdict] | None = None,
        dedicated: list[tuple[str, list[str]]] | None = None,
        max_checks: int = 10,
    ) -> tuple[Dict[str, Any], mock.MagicMock, mock.MagicMock]:
        client = mock.MagicMock()
        client.system_one.return_value = _jev_response(SAFE_NOULS)
        photo_checker = mock.MagicMock(spec=PhotoChecker)
        photo_checker.enabled = True
        photo_checker.check.side_effect = lambda url, dishes, text: (photo_verdicts or {}).get(
            url.rsplit("/", 1)[-1].removesuffix(".jpg")
        )
        photo_checker.comment_fits.return_value = CommentVerdict(fits=True, reason="ok")
        retweeter = AutoQuoteRetweeter(
            db_manager=_make_db_mock(),
            dry_run=True,
            jev_checker=JevChecker(api_key="fake", client=client),
            photo_checker=photo_checker,
        )
        retweeter.dry_run = False
        retweeter.content_generator._specific_keyword_comments = dedicated or []

        def judge(checker: Any, tweet_id: str, text: str, photo_url: str | None = None) -> Any:
            value = meat_main.get(tweet_id)
            return None if value is None else MeatFocusVerdict(value, with_photo=photo_url is not None)

        with (
            mock.patch.object(retweeter, "_fetch_timeline_with_retry", return_value=timeline),
            mock.patch.object(retweeter, "_fetch_search_candidates", return_value=[]),
            mock.patch.object(retweeter.twitter_client, "pseudo_quote_tweet", return_value="q1") as post,
            mock.patch("nikune.auto_quote_retweeter.judge_meat_focus", side_effect=judge) as judge_mock,
            mock.patch("nikune.auto_quote_retweeter.MEAT_FOCUS_CHECK_MAX_PER_RUN", max_checks),
        ):
            results = retweeter.check_and_quote_tweets()
        return results, post, judge_mock

    def test_meat_as_a_side_ingredient_loses_to_a_real_meat_post(self) -> None:
        photo_verdicts = {"noodles": PhotoVerdict(is_food=True, shows_meat=True, dishes=["牛肉"])}
        timeline = [_photo_tweet("noodles", "そうめんに牛肉と焼肉のタレ"), _food_tweet("steak", "ステーキたべた")]

        results, post, judge = self._run({"noodles": 0.15, "steak": 0.95}, timeline, photo_verdicts)

        self.assertEqual(post.call_args.args[0], "steak")
        self.assertEqual(results["meat_focus_checked"], 2)
        self.assertEqual(results["not_meat_main"], 1)
        # 写真付きの候補には写真のURLを渡す
        self.assertEqual(judge.call_args_list[0].args[3], "https://example.com/noodles.jpg")

    def test_side_meat_post_without_a_dedicated_comment_is_not_quoted(self) -> None:
        photo_verdicts = {"noodles": PhotoVerdict(is_food=True, shows_meat=True, dishes=["牛肉"])}

        results, post, _ = self._run(
            {"noodles": 0.15}, [_photo_tweet("noodles", "そうめんに牛肉と焼肉のタレ")], photo_verdicts
        )

        # 肉のキーワードを外すと食べ物の話題でもなくなる（「そうめん」はキーワードにない）
        post.assert_not_called()
        self.assertEqual(results["not_meat_main"], 1)

    def test_side_meat_post_gets_the_dish_comment_not_a_meat_one(self) -> None:
        dedicated = [("焼肉", ["焼肉のセリフ"]), ("ラーメン", ["ラーメンのセリフ"])]

        _, post, _ = self._run({"t1": 0.1}, [_food_tweet("t1", "焼肉のタレで作ったラーメン")], dedicated=dedicated)

        comment = post.call_args.args[2]
        self.assertIn("ラーメンのセリフ", comment)
        self.assertNotIn("焼肉のセリフ", comment)
        self.assertNotIn("🥩", comment)
        self.assertNotIn("🍖", comment)

    def test_unavailable_judgement_keeps_the_meat_ranking(self) -> None:
        results, post, _ = self._run({}, [_food_tweet("t1", "焼肉たべた")])

        self.assertEqual(post.call_args.args[0], "t1")
        self.assertEqual(results["meat_focus_unavailable"], 1)
        self.assertEqual(results["not_meat_main"], 0)

    def test_only_meat_candidates_are_judged_up_to_the_limit(self) -> None:
        timeline = [
            _food_tweet("sushi", "寿司たべた"),
            _food_tweet("m1", "焼肉たべた"),
            _food_tweet("m2", "牛肉たべた"),
            _food_tweet("m3", "ステーキたべた"),
        ]

        _, _, judge = self._run({"m1": 0.9, "m2": 0.9, "m3": 0.9}, timeline, max_checks=2)

        self.assertEqual([c.args[1] for c in judge.call_args_list], ["m1", "m2"])

    def test_not_judged_without_a_jev_key(self) -> None:
        retweeter = AutoQuoteRetweeter(db_manager=_make_db_mock(), dry_run=True)
        results: Dict[str, Any] = {"meat_focus_checked": 0, "meat_focus_unavailable": 0, "not_meat_main": 0}

        with mock.patch("nikune.auto_quote_retweeter.judge_meat_focus") as judge:
            not_meat = retweeter._check_meat_focus([_food_tweet("t1", "焼肉たべた")], {}, results)

        judge.assert_not_called()
        self.assertEqual(not_meat, set())
