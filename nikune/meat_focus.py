"""
引用RT候補で「肉が主役か」を Jev に判定させる

キーワードや写真の判定（Claude）は「肉が入っているか・写っているか」しか見ていないため、
肉が具として少し乗っているだけの投稿（牛肉の乗ったそうめん、「焼肉のタレ」を使った料理など）も
肉の話題として最優先にしていた。肉の話題に入る候補だけ、Jev に「肉が主役か」を1問だけ聞き、
主役でなければ肉の話題から外す（専用コメントのある食べ物として扱うか、引用しない）。

写真があれば本文と一緒に1枚目を見せる。本文が店名や値段だけの投稿（ハンバーグの写真など）は、
写真がないと主役が肉だと分からないため。画像の入力は TypeSafe では試験的な機能なので、
写真付きで判定できなかったときは本文だけで聞き直す。それも失敗したら判定なし（従来どおり）。

安全判定（nikune/quote_safety.py）の質問とは別のリクエストにしている。安全判定のしきい値は
本文だけで調整したもので、写真を足すと値が変わりうるため。
"""

import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

import requests
from typesafe_sdk import JSONContent, Noul

from nikune.jev_checker import JevChecker, JevImage
from nikune.quote_safety import QUOTING_ACCOUNT_DESCRIPTION

logger = logging.getLogger(__name__)

# --- しきい値 -------------------------------------------------------------
# 過去の引用候補42本（写真付き39本）を jev-1.13.0 に写真付きで通した結果から決めた。
# 肉が主役の投稿（焼肉・牛タン定食・焼き鳥・もつ煮・ハンバーグなど）は 0.72〜0.98、
# 主役でない投稿（寿司・ラーメン・牛肉の乗ったそうめん・チャーハンなど）は 0.01〜0.19 と大きく離れていた。
# どちらとも言えない投稿（鶏飯・肉入りのカレーなど）は 0.5〜0.6 前後に集まり、肉の話題から外れる。
# 本文だけで聞くと、本文に肉のことが書かれていない投稿（とり天丼・ハンバーグ）が 0.1 前後になる。
# モデルのバージョンを上げるときは同じ検証をやり直すこと。
MEAT_MAIN_THRESHOLD = 0.65

MEAT_MAIN_KEY = "meat_main"
# 判定できなかったときのログの書き出し（scripts/check_logs.py がこれを見て通知する）
PHOTO_UNAVAILABLE_MARKER = "🥩 Meat focus with photo unavailable"
UNAVAILABLE_MARKER = "🥩 Meat focus unavailable"
# State の中で写真を指す参照名（Jev に送る画像の名前。値に意味はない）
PHOTO_REF = "9c41e7a2-candidate-photo"

# 写真の取得: Jev に送る画像の上限と、X の画像を小さいサイズで取るための指定
PHOTO_FETCH_TIMEOUT_SECONDS = 10.0
MAX_PHOTO_BYTES = 5 * 1024 * 1024
X_IMAGE_HOST = "pbs.twimg.com"
PHOTO_FORMATS = {"image/jpeg": "jpg", "image/png": "png"}

_MEAT_DEFINITION = "meat (beef, pork, chicken, lamb, offal, or processed meat such as ham or sausage)"


def _question(with_photo: bool) -> Noul:
    target = "the post (`candidate_post.text` and `candidate_post.photo`)" if with_photo else "`candidate_post.text`"
    return Noul(
        instructions=(
            f"Is {_MEAT_DEFINITION} the main subject of {target}, rather than just one ingredient, "
            "a seasoning, or a side element?"
        ),
        criteria={
            "true": "The post is mainly about a meat dish or eating meat (steak, yakiniku, grilled skewers, "
            "fried chicken, hamburger steak, etc.), so a reaction like 'Meat!' fits the main point.",
            "false": "The main subject is something else (noodles, rice, vegetables, fish, sweets, a restaurant "
            "in general), and meat only appears as an ingredient, a sauce name, or a minor detail.",
        },
    )


@dataclass(frozen=True)
class MeatFocusVerdict:
    """「肉が主役か」の判定結果

    probability: 肉が主役である確率（0〜1）
    with_photo: 写真も見て判定したか
    """

    probability: float
    with_photo: bool
    model: Optional[str] = None

    @property
    def is_meat_main(self) -> bool:
        return self.probability >= MEAT_MAIN_THRESHOLD


def fetch_photo(url: str) -> Optional[JevImage]:
    """写真を取ってくる。取れなかったら None（例外は投げない）

    X の画像は小さいサイズ（長辺680px）で取る。検証もこの大きさで行った。
    """
    parts = urlsplit(url)
    if parts.hostname == X_IMAGE_HOST and not parts.query:
        url = f"{url}?name=small"
    try:
        response = requests.get(url, timeout=PHOTO_FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        photo_format = PHOTO_FORMATS.get(content_type)
        if photo_format is None or not response.content or len(response.content) > MAX_PHOTO_BYTES:
            logger.warning(f"⚠️ Photo not usable for the meat check: type={content_type} bytes={len(response.content)}")
            return None
        return JevImage(data=response.content, format=photo_format)
    except Exception as e:  # noqa: BLE001 - 写真が取れなくても本文だけで判定を続ける
        logger.warning(f"⚠️ Failed to fetch photo for the meat check: {type(e).__name__}")
        return None


def judge_meat_focus(
    checker: JevChecker, tweet_id: str, text: str, photo_url: Optional[str] = None
) -> Optional[MeatFocusVerdict]:
    """候補の「肉が主役か」を判定する。キー未設定・判定できなかったときは None（例外は投げない）"""
    if not checker.enabled:
        return None

    image = fetch_photo(photo_url) if photo_url else None
    if image is not None:
        photo_state: JSONContent = {
            "quoting_account": QUOTING_ACCOUNT_DESCRIPTION,
            "candidate_post": {"text": text, "photo": PHOTO_REF},
        }
        result = checker.ask(photo_state, {MEAT_MAIN_KEY: _question(True)}, images={PHOTO_REF: image})
        if result.ok:
            verdict = MeatFocusVerdict(result.nouls[MEAT_MAIN_KEY], with_photo=True, model=result.model)
            logger.info(_format_log(tweet_id, verdict))
            return verdict
        # 写真の取得ではなく Jev 側で失敗したとき（試験的な機能の形式が変わったなど）。
        # 本文だけで続けるが、黙って写真なしの判定に落ちないよう scripts/check_logs.py が通知する
        logger.warning(f"{PHOTO_UNAVAILABLE_MARKER}: tweet={tweet_id} ({result.error}), retrying without the photo")

    text_state: JSONContent = {"quoting_account": QUOTING_ACCOUNT_DESCRIPTION, "candidate_post": {"text": text}}
    result = checker.ask(text_state, {MEAT_MAIN_KEY: _question(False)})
    if not result.ok:
        logger.warning(f"{UNAVAILABLE_MARKER}: tweet={tweet_id} ({result.error})")
        return None
    verdict = MeatFocusVerdict(result.nouls[MEAT_MAIN_KEY], with_photo=False, model=result.model)
    logger.info(_format_log(tweet_id, verdict))
    return verdict


def _format_log(tweet_id: str, verdict: MeatFocusVerdict) -> str:
    return (
        f"🥩 Meat focus: tweet={tweet_id} meat_main={verdict.probability:.2f} "
        f"main={verdict.is_meat_main} photo={verdict.with_photo} model={verdict.model}"
    )
