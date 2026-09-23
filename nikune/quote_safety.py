"""
引用RT候補の安全判定（Jev による二次フィルタ）

キーワード一致（ContentGenerator.get_food_keyword_score() と NG ワード正規表現）を
通過した候補にだけ、引用コメント生成・投稿の前に Jev へ1リクエストで問い合わせる。
キーワード一致を置き換えるものではない。

判定ルール（evaluate_quote_candidate）:
    1. 「避けたい」系 Noul のどれかが AVOID_THRESHOLD 以上 → 引用しない
    2. 「引用に適しているか」の Noul が SUITABLE_THRESHOLD 未満 → 引用しない
    3. どの Noul でも 0.5 ± UNCERTAIN_MARGIN の範囲（あいまい帯）なら → 引用しない
       （Noul の 0.5 は「中くらい」ではなく「yes と no が同程度 = わからない」の意味）
    4. Jev が失敗したら → 引用しない（判定不可）
    5. API キー未設定（機能オフ）なら → 従来どおり（Jev なしで引用処理へ進む）
Score（反応する価値）は現状ログに残すだけで、判定には使わない。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from typesafe_sdk import JSONContent, Noul, Score

from nikune.jev_checker import JevChecker, JevQuestion

logger = logging.getLogger(__name__)

# --- しきい値 -------------------------------------------------------------
# 誤って不適切な投稿を引用するコスト（公開アカウントでの炎上・加担）は、
# 適切な候補を1件見送るコスト（次の候補・次回実行がある）よりずっと大きい。
# そのため「避けたい」系は低め、「適している」は高めに置き、迷ったら引用しない側に倒す。
# 値は scratchpad の検証セット（食中毒・炎上・訃報・宣伝などの落としたい例と、
# 普通に楽しい食べ物の投稿）を jev-1.13.0 に通した結果を見て決めた。
# 検証では、落としたい例は少なくとも1つの「避けたい」系が 0.9 以上、普通の食べ物の投稿は
# 「避けたい」系がすべて 0.15 未満・「適している」が 0.9 以上と大きく離れていた。
# 飲食店の「数量限定・お早めに」のような軽い販促は promotion が 0.4 前後（あいまい帯）になり、引用しない側に倒れる。
# モデルのバージョンを上げるときは同じ検証をやり直すこと。
AVOID_THRESHOLD = 0.3
SUITABLE_THRESHOLD = 0.7
# あいまい帯: 0.5 ± この幅に入る Noul は「判断がつかない」とみなす。
# 上のしきい値だけでも多くはカバーされるが、しきい値を将来緩めてもこの規則が残るよう独立に持つ
UNCERTAIN_MARGIN = 0.15

# --- 質問 -----------------------------------------------------------------
# 質問のキーはモデルに送られない（コード側の識別子）。意味はすべて instructions / criteria に書く。
# Jev の精度は英語が最も高いため、質問文は英語で書き、投稿本文（日本語）は State に入れる。
SUITABLE_KEY = "suitable_food_topic"
AVOID_KEYS = (
    "tragedy_context",
    "controversy_context",
    "promotion_context",
    "offensive_content",
)
VALUE_SCORE_KEY = "reaction_value"

QUOTE_SAFETY_QUESTIONS: Dict[str, JevQuestion] = {
    SUITABLE_KEY: Noul(
        instructions=(
            "Is `candidate_post.text` a light, positive post about food, cooking, eating, or a restaurant "
            "that the account described in `quoting_account` could safely quote with a cheerful comment?"
        ),
        criteria={
            "true": "The post is mainly about enjoying, making, or looking forward to food, and a cheerful "
            "food-loving reaction would be natural and welcome.",
            "false": "Food is not the main topic, or the post's situation makes a cheerful reaction "
            "inappropriate, insensitive, or awkward.",
        },
    ),
    "tragedy_context": Noul(
        instructions=(
            "Does `candidate_post.text` involve an accident, incident, crime, disaster, food poisoning, "
            "illness, injury, or someone's death, so that a cheerful reaction would look like mocking it?"
        ),
        criteria={
            "true": "The post mentions or is set against such an event, even if food also appears.",
            "false": "No such event is involved.",
        },
    ),
    "controversy_context": Noul(
        instructions=(
            "Does `candidate_post.text` deal with politics, religion, a social conflict, or a public "
            "controversy or backlash (for example a restaurant being criticized or boycotted)?"
        ),
        criteria={
            "true": "The post takes part in or refers to such a political, religious, or controversial topic.",
            "false": "The post has nothing to do with such topics.",
        },
    ),
    "promotion_context": Noul(
        instructions=(
            "Is `candidate_post.text` paid advertising, sponsored content, an affiliate or referral link, "
            "a follow/repost giveaway or campaign, a solicitation (such as side-business or recruitment), "
            "or a hard sales pitch, so that quoting it would help spread the promotion?"
        ),
        criteria={
            "true": "The post is an ad, sponsored (#PR/#ad), pushes a purchase link or discount code, runs a "
            "giveaway or repost campaign, or solicits people to join, contact, or sign up.",
            "false": "The post is a personal post, or a restaurant's ordinary note about its opening hours or "
            "today's menu with no campaign, purchase link, discount, or solicitation.",
        },
    ),
    "offensive_content": Noul(
        instructions=(
            "Does `candidate_post.text` contain sexual, violent, hateful, or discriminatory expressions, "
            "including indirect wording or slang for them?"
        ),
        criteria={
            "true": "Such expressions are present.",
            "false": "No such expressions are present.",
        },
    ),
    VALUE_SCORE_KEY: Score(
        instructions=(
            "How much would the account described in `quoting_account` want to react to `candidate_post.text`?"
        ),
        criteria=[
            "Not worth reacting to: food is absent or incidental.",
            "Somewhat worth reacting to: food is mentioned but the post is not really about it.",
            "Worth reacting to: an ordinary post about eating or cooking something.",
            "Very worth reacting to: an enthusiastic post about delicious food, especially meat.",
        ],
    ),
}

# State に入れる引用側アカウントの説明（公開済みの README の範囲の中立的な説明のみ）
QUOTING_ACCOUNT_DESCRIPTION = (
    "A cheerful character bot on X that loves food, especially meat. "
    "It quote-posts other people's posts about food with a short, upbeat comment."
)

QuoteDecision = Literal["quote", "skip", "unavailable", "disabled"]


@dataclass(frozen=True)
class QuoteSafetyVerdict:
    """引用RT候補1件の判定結果

    decision:
        "quote"       Jev が引用してよいと判定した
        "skip"        Jev の判定で引用しない
        "unavailable" Jev が失敗して判定できなかった（引用しない）
        "disabled"    API キー未設定で Jev を使っていない（従来どおり引用処理へ進む）
    """

    decision: QuoteDecision
    reasons: List[str] = field(default_factory=list)
    nouls: Dict[str, float] = field(default_factory=dict)
    value_score: Optional[float] = None
    model: Optional[str] = None
    error: Optional[str] = None

    @property
    def should_quote(self) -> bool:
        return self.decision in ("quote", "disabled")


def build_quote_candidate_state(tweet_text: str, author_username: Optional[str]) -> JSONContent:
    """Jev に渡す State（判断に必要な最小限の文脈だけ）"""
    return {
        "quoting_account": QUOTING_ACCOUNT_DESCRIPTION,
        "candidate_post": {
            "author": f"@{author_username}" if author_username else "unknown",
            "text": tweet_text,
        },
    }


def is_uncertain(probability: float) -> bool:
    """Noul が 0.5 付近（yes と no が同程度 = わからない）か"""
    return abs(probability - 0.5) < UNCERTAIN_MARGIN


def decide(nouls: Dict[str, float]) -> List[str]:
    """Noul の値から「引用しない理由」を列挙する（空なら引用してよい）"""
    reasons: List[str] = []
    for key in AVOID_KEYS:
        if nouls[key] >= AVOID_THRESHOLD:
            reasons.append(f"{key}>={AVOID_THRESHOLD}")
    if nouls[SUITABLE_KEY] < SUITABLE_THRESHOLD:
        reasons.append(f"{SUITABLE_KEY}<{SUITABLE_THRESHOLD}")
    for key, value in nouls.items():
        if is_uncertain(value):
            reasons.append(f"{key}~0.5(uncertain)")
    return reasons


def evaluate_quote_candidate(
    checker: JevChecker, tweet_id: str, tweet_text: str, author_username: Optional[str]
) -> QuoteSafetyVerdict:
    """引用RT候補を Jev で判定し、1行のログを残して結果を返す。例外は投げない"""
    try:
        result = checker.ask(build_quote_candidate_state(tweet_text, author_username), QUOTE_SAFETY_QUESTIONS)
        if result.status == "disabled":
            verdict = QuoteSafetyVerdict(decision="disabled")
        elif not result.ok:
            verdict = QuoteSafetyVerdict(decision="unavailable", error=result.error, model=result.model)
        else:
            reasons = decide(result.nouls)
            verdict = QuoteSafetyVerdict(
                decision="skip" if reasons else "quote",
                reasons=reasons,
                nouls=result.nouls,
                value_score=result.scores.get(VALUE_SCORE_KEY),
                model=result.model,
            )
    except Exception as e:  # noqa: BLE001 - 判定ロジック側の想定外エラーでも止めない
        verdict = QuoteSafetyVerdict(decision="unavailable", error=f"{type(e).__name__}: {e}")

    if verdict.decision != "disabled":
        logger.info(format_verdict_log(tweet_id, verdict))
    return verdict


def format_verdict_log(tweet_id: str, verdict: QuoteSafetyVerdict) -> str:
    """候補ごとの1行ログ: tweet id・各 Noul・Score・最終判断"""
    label = {"quote": "QUOTE", "skip": "SKIP", "unavailable": "UNAVAILABLE", "disabled": "DISABLED"}[verdict.decision]
    nouls = " ".join(f"{k}={v:.2f}" for k, v in verdict.nouls.items()) or "-"
    score = f"{verdict.value_score:.2f}" if verdict.value_score is not None else "-"
    parts = [f"🧭 Jev quote check: tweet={tweet_id}", f"decision={label}", f"nouls[{nouls}]", f"value_score={score}"]
    if verdict.reasons:
        parts.append(f"reasons={','.join(verdict.reasons)}")
    if verdict.model:
        parts.append(f"model={verdict.model}")
    if verdict.error:
        parts.append(f"error={verdict.error}")
    return " ".join(parts)
