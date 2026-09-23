"""
自分の投稿の投稿直前チェック（Jev）

twitter_client.post_tweet() の直前に、投稿文を Jev へ1リクエストで問い合わせる。
現段階は「判定の傾向を見る」ための**警告のみ**で、どんな判定結果でも投稿は止めない。

判定ルール（decide）と「止めるかどうか」（should_post）は分けてある:
    - decide(): Noul の値から「問題あり」とみなす理由を列挙する。理由が1つでもあれば decision="warn"
      （= would_block。止める運用にしたら止まる投稿）
    - should_post(): 最終的に投稿するかどうか。BLOCK_ON_WARN が False の間は常に True
将来「止める」に切り替えるときは BLOCK_ON_WARN を True にする（UNCHECKED = Jev 失敗時も止めるなら
BLOCK_ON_UNCHECKED も True にする）。呼び出し側（SchedulerManager）は should_post() の戻り値に従う作りになっている。

最終判断:
    OK        Jev が問題なしと判定した
    WARN      Jev の判定で問題あり（would_block）。現状は警告ログを出して投稿する
    UNCHECKED Jev が失敗して判定できなかった。「チェックできなかった」警告を出して投稿する
    DISABLED  API キー未設定で Jev を使っていない（従来どおり投稿する）

質問1（ペルソナとの一致）は本番ペルソナ data/persona.tsv（gitignore 対象）がある場合だけ行う。
docs/CHARACTER_PERSONA_SAMPLE.md はサンプルで本番と一致しないため代用しない。
"""

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

from typesafe_sdk import JSONContent, Noul

from nikune.jev_checker import JevChecker, JevQuestion
from nikune.quote_safety import is_uncertain

logger = logging.getLogger(__name__)

# 本番ペルソナ（非公開シート「tweet_template」の persona タブのエクスポート。gitignore 対象）。
# 形式: UTF-8・タブ区切り・1行目がヘッダー（分類 / 項目 / 内容 / 補足）。
# quote_comments.tsv と同じく、カレントディレクトリ（リポジトリルート）からの相対パスで持つ
PERSONA_FILE = "data/persona.tsv"
_PERSONA_COLUMNS = {"分類": "category", "項目": "item", "内容": "content", "補足": "note"}
_PERSONA_REQUIRED_HEADERS = ("分類", "項目", "内容")

# --- 「止める」かどうか（判定ルールとは独立） --------------------------------
# ユーザー方針（2026-09）: まず判定の傾向を見るため、どんな判定でも投稿は止めない
BLOCK_ON_WARN = False
BLOCK_ON_UNCHECKED = False

# --- しきい値 -------------------------------------------------------------
# 警告のみの段階なので、まずは引用RT（quote_safety.py）と同じ値から始める。
# 実運用のログ（各 Noul の値）を見てから調整すること。
# あいまい帯（0.5 ± quote_safety.UNCERTAIN_MARGIN）は quote_safety.is_uncertain() をそのまま使って揃える
AVOID_THRESHOLD = 0.3
PERSONA_CONSISTENT_THRESHOLD = 0.7

# --- 質問 -----------------------------------------------------------------
# 質問のキーはモデルに送られない（コード側の識別子）。意味はすべて instructions / criteria に書く。
# Jev の精度は英語が最も高いため質問文は英語で書き、投稿本文・ペルソナ（日本語）は State に入れる。
PERSONA_KEY = "persona_consistent"
PROMOTION_KEY = "promotional"
OFFENSIVE_KEY = "misleading_or_offensive"
AVOID_KEYS = (PROMOTION_KEY, OFFENSIVE_KEY)

PERSONA_QUESTION = Noul(
    instructions=(
        "`post.text` is a post written by the character described in `persona` (a list of rules about the "
        "character's personality, first-person pronoun, speech style, sentence endings, forms of address, "
        "and habits). Is the post consistent with this character's voice, personality, and world? "
        "The leading 🐻 is the account's fixed signature and is not part of the character's speech. "
        "Judge the character and style only, not the topic or factual accuracy."
    ),
    criteria={
        "true": (
            "The post sounds like this character. This includes deliberate departures from the usual voice "
            "that the persona itself explains, for example quoting a line from a movie, drama, or other work "
            "when the persona says the character likes to memorize and repeat such lines; a quoted line may "
            "use a different politeness level or first-person pronoun without being inconsistent."
        ),
        "false": (
            "The post uses a voice, pronoun, personality, or worldview that contradicts the persona, and "
            "nothing in the persona explains the difference."
        ),
    },
)

PROMOTION_QUESTION = Noul(
    instructions=(
        "Would readers see `post.text` as advertising, a sales pitch, sponsored content, or a solicitation, "
        "such as urging people to buy something, visit a specific shop, sign up, follow, repost, click a link, "
        "or join something?"
    ),
    criteria={
        "true": "The post promotes a product, shop, service, or campaign, or asks readers to take such an action.",
        "false": (
            "The post is an ordinary personal remark about food or daily life, even if it names a food, a dish, "
            "or a kind of restaurant."
        ),
    },
)

OFFENSIVE_QUESTION = Noul(
    instructions=(
        "Could `post.text` mislead readers or make them uncomfortable? This includes stating something false "
        "or risky as fact (for example health, diet, or food-safety claims), or wording that could read as "
        "sexual, violent, hateful, discriminatory, mocking, or insensitive to a group or a real event."
    ),
    criteria={
        "true": "Some wording is likely to be misread, spread misinformation, or offend or upset ordinary readers.",
        "false": (
            "A harmless, light post that ordinary readers would understand as intended, including playful "
            "exaggeration about loving food."
        ),
    },
)

# State に入れるアカウントの説明（公開済みの README の範囲の中立的な説明のみ）
ACCOUNT_DESCRIPTION = (
    "A character bot on X that loves food, especially meat, and posts short standalone posts in Japanese. "
    "Every post starts with a 🐻 signature."
)

PostDecision = Literal["ok", "warn", "unchecked", "disabled"]
_DECISION_LABELS: Dict[str, str] = {"ok": "OK", "warn": "WARN", "unchecked": "UNCHECKED", "disabled": "DISABLED"}


@dataclass(frozen=True)
class PostSafetyVerdict:
    """投稿1件の投稿直前チェック結果"""

    decision: PostDecision
    reasons: List[str] = field(default_factory=list)
    nouls: Dict[str, float] = field(default_factory=dict)
    persona_checked: bool = False
    model: Optional[str] = None
    error: Optional[str] = None

    @property
    def would_block(self) -> bool:
        """「止める」運用にした場合に止まる判定か（現状はログに出すだけ）"""
        return self.decision == "warn"

    @property
    def label(self) -> str:
        return _DECISION_LABELS[self.decision]


def should_post(verdict: PostSafetyVerdict) -> bool:
    """最終的に投稿するかどうか。現状の方針（警告のみ）では常に True"""
    if verdict.decision == "warn" and BLOCK_ON_WARN:
        return False
    if verdict.decision == "unchecked" and BLOCK_ON_UNCHECKED:
        return False
    return True


def load_persona(path: str = PERSONA_FILE) -> Optional[List[Dict[str, str]]]:
    """
    本番ペルソナを読み込む。ファイルがない・読めない・形式が違う場合は None（質問1を行わない）

    Returns:
        [{"category": 分類, "item": 項目, "content": 内容, "note": 補足(空なら省略)}, ...]
    """
    persona_path = Path(path)
    if not persona_path.exists():
        return None
    try:
        # utf-8-sig: 先頭に BOM があっても読めるように。newline="": CRLF を csv モジュールに任せる
        with open(persona_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            headers = [h.strip() for h in (reader.fieldnames or [])]
            if not all(h in headers for h in _PERSONA_REQUIRED_HEADERS):
                logger.warning(f"⚠️ {path} のヘッダーが想定と異なるため、ペルソナとの一致チェックを行いません")
                return None
            rows: List[Dict[str, str]] = []
            for raw in reader:
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if isinstance(v, str)}
                entry = {_PERSONA_COLUMNS[k]: v for k, v in row.items() if k in _PERSONA_COLUMNS and v}
                if entry.get("content"):
                    rows.append(entry)
        if not rows:
            logger.warning(f"⚠️ {path} に有効な行がないため、ペルソナとの一致チェックを行いません")
            return None
        return rows
    except Exception as e:  # noqa: BLE001 - 読み込み失敗でも投稿処理は止めない
        logger.warning(f"⚠️ Failed to load {path} ({type(e).__name__}); skipping the persona consistency check")
        return None


def build_post_state(text: str, persona: Optional[List[Dict[str, str]]]) -> JSONContent:
    """Jev に渡す State（判断に必要な文脈だけ）"""
    state: Dict[str, JSONContent] = {"account": ACCOUNT_DESCRIPTION, "post": {"text": text}}
    if persona is not None:
        state["persona"] = [dict(row) for row in persona]
    return state


def build_post_questions(persona_available: bool) -> Dict[str, JevQuestion]:
    """ペルソナがあるときだけ質問1（ペルソナとの一致）を含める"""
    questions: Dict[str, JevQuestion] = {}
    if persona_available:
        questions[PERSONA_KEY] = PERSONA_QUESTION
    questions[PROMOTION_KEY] = PROMOTION_QUESTION
    questions[OFFENSIVE_KEY] = OFFENSIVE_QUESTION
    return questions


def decide(nouls: Dict[str, float]) -> List[str]:
    """Noul の値から「問題あり」とみなす理由を列挙する（空なら OK）。止めるかどうかは should_post() が決める"""
    reasons: List[str] = []
    for key in AVOID_KEYS:
        if key in nouls and nouls[key] >= AVOID_THRESHOLD:
            reasons.append(f"{key}>={AVOID_THRESHOLD}")
    if PERSONA_KEY in nouls and nouls[PERSONA_KEY] < PERSONA_CONSISTENT_THRESHOLD:
        reasons.append(f"{PERSONA_KEY}<{PERSONA_CONSISTENT_THRESHOLD}")
    for key, value in nouls.items():
        if is_uncertain(value):
            reasons.append(f"{key}~0.5(uncertain)")
    return reasons


def evaluate_post(
    checker: JevChecker,
    text: str,
    route: str,
    template_id: Optional[int] = None,
    persona_path: str = PERSONA_FILE,
) -> PostSafetyVerdict:
    """投稿文を Jev で判定し、1行のログを残して結果を返す。例外は投げない"""
    try:
        persona = load_persona(persona_path) if checker.enabled else None
        result = checker.ask(build_post_state(text, persona), build_post_questions(persona is not None))
        if result.status == "disabled":
            verdict = PostSafetyVerdict(decision="disabled")
        elif not result.ok:
            verdict = PostSafetyVerdict(
                decision="unchecked", persona_checked=persona is not None, error=result.error, model=result.model
            )
        else:
            reasons = decide(result.nouls)
            verdict = PostSafetyVerdict(
                decision="warn" if reasons else "ok",
                reasons=reasons,
                nouls=result.nouls,
                persona_checked=persona is not None,
                model=result.model,
            )
    except Exception as e:  # noqa: BLE001 - 判定ロジック側の想定外エラーでも投稿は止めない
        verdict = PostSafetyVerdict(decision="unchecked", error=f"{type(e).__name__}: {e}")

    message = format_verdict_log(route, template_id, verdict)
    if verdict.decision in ("warn", "unchecked"):
        logger.warning(message)
    else:
        logger.info(message)
    return verdict


def format_verdict_log(route: str, template_id: Optional[int], verdict: PostSafetyVerdict) -> str:
    """投稿ごとの1行ログ: 経路・テンプレートID・各 Noul・最終判断（投稿本文は出さない）"""
    nouls = " ".join(f"{k}={v:.2f}" for k, v in verdict.nouls.items()) or "-"
    parts = [
        f"🧭 Jev pre-post check: route={route}",
        f"template={template_id if template_id is not None else '-'}",
        f"decision={verdict.label}",
        f"nouls[{nouls}]",
    ]
    if verdict.decision in ("ok", "warn", "unchecked"):
        parts.append(f"persona={'checked' if verdict.persona_checked else 'skipped(no data/persona.tsv)'}")
    if verdict.reasons:
        parts.append(f"reasons={','.join(verdict.reasons)}")
    if verdict.decision == "warn":
        action = "blocked" if not should_post(verdict) else "posting anyway (warn-only mode)"
        parts.append(f"action={action}")
    if verdict.decision == "unchecked":
        action = "blocked" if not should_post(verdict) else "posting without the check"
        parts.append(f"action={action}")
    if verdict.model:
        parts.append(f"model={verdict.model}")
    if verdict.error:
        parts.append(f"error={verdict.error}")
    return " ".join(parts)
