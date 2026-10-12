"""
引用RT候補の写真を Claude に見せて、料理・肉が写っているかを判定するモジュール

本文のキーワード一致だけでは、「店名や日付だけの本文＋料理の写真」という投稿の中身が分からない。
写真を1枚見て「食べ物の写真か」「肉が写っているか」「何の料理か」だけを答えてもらい、
引用する候補の順位付けとセリフ選びに使う。文章は生成させない。

設計上の約束（nikune/jev_checker.py と同じ）:
    - API キー未設定なら機能オフ（check() は None を返す）。例外にしない。警告ログはプロセスで1回だけ
    - どんな失敗（タイムアウト・ネットワーク・認証/課金エラー・判定の拒否・想定外の応答）でも
      例外を呼び出し元に投げず、None を返す。呼び出し側は本文だけのルールで続行する
    - API キーはログ・例外メッセージ・戻り値に一切含めない
"""

import logging
import threading
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

import anthropic
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)

# SDK 内部のリトライ（429/5xx/接続エラー/タイムアウト対象）。cron 実行を長く止めないよう1回だけ
DEFAULT_MAX_RETRIES = 1
# エラーメッセージを残す最大文字数（サーバー応答本文が長い場合の保険）
MAX_ERROR_MESSAGE_LENGTH = 200

_PROMPT = """この画像は、SNSの投稿に添付された写真です。次の3点を判定してください。

- is_food: 料理・食べ物が主役の写真かどうか（店の外観、メニュー表、人物、風景などは false）
- shows_meat: 肉（牛・豚・鶏・羊などの肉、肉料理、ハムやベーコンなどの加工肉）がはっきり写っているかどうか。
  魚介類・卵・豆腐は肉に含めない。肉が入っていそうでも見えていなければ false
- dishes: 写っている料理に当てはまるものを、下の一覧からそのままの表記で選ぶ。
  当てはまるものがなければ空にする。はっきり分からないものは選ばない

一覧: {dishes}"""

_missing_key_warned = False
_missing_key_lock = threading.Lock()


class _PhotoAnswer(BaseModel):
    """Claude に返してもらう答えの形"""

    is_food: bool
    shows_meat: bool
    dishes: List[str]


@dataclass(frozen=True)
class PhotoVerdict:
    """写真1枚の判定結果

    Attributes:
        is_food: 料理・食べ物が主役の写真か
        shows_meat: 肉がはっきり写っているか
        dishes: 写っている料理（問い合わせ時に渡した一覧に含まれるものだけ）
        model: 実際に応答したモデル
    """

    is_food: bool
    shows_meat: bool
    dishes: List[str]
    model: Optional[str] = None


class PhotoChecker:
    """写真1枚を Claude に見せて判定を受け取る"""

    def __init__(
        self,
        api_key: Optional[str],
        model: str,
        timeout_seconds: float,
        client: Optional[Any] = None,
    ) -> None:
        """
        Args:
            client: テスト用の差し替え口。省略時は api_key から Anthropic クライアントを作る
        """
        self.model = model
        self._client: Optional[Any] = client
        if client is None and api_key:
            self._client = anthropic.Anthropic(
                api_key=api_key, timeout=timeout_seconds, max_retries=DEFAULT_MAX_RETRIES
            )

    @classmethod
    def from_settings(cls) -> "PhotoChecker":
        """設定（ANTHROPIC_API_KEY 等）から生成する"""
        return cls(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.PHOTO_CHECK_MODEL,
            timeout_seconds=settings.PHOTO_CHECK_TIMEOUT_SECONDS,
        )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def check(self, image_url: str, dish_keywords: Sequence[str]) -> Optional[PhotoVerdict]:
        """写真を判定する。判定できなかったとき（機能オフ・失敗・拒否）は None を返す

        Args:
            image_url: 写真の公開URL
            dish_keywords: 料理名の一覧。dishes はこの中からだけ返る
        """
        if self._client is None:
            self._warn_missing_key_once()
            return None

        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=16000,
                # 見て答えるだけの単純な判定なので、考える量は最小にする
                output_config={"effort": "low"},
                output_format=_PhotoAnswer,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "url", "url": image_url}},
                            {"type": "text", "text": _PROMPT.format(dishes="、".join(dish_keywords))},
                        ],
                    }
                ],
            )
        except Exception as e:
            # anthropic の例外メッセージにキーは含まれないが、長い応答本文に備えて切り詰める
            logger.warning(f"📷 Photo check unavailable: {type(e).__name__}: {str(e)[:MAX_ERROR_MESSAGE_LENGTH]}")
            return None

        answer = getattr(response, "parsed_output", None)
        if getattr(response, "stop_reason", None) == "refusal" or not isinstance(answer, _PhotoAnswer):
            logger.warning(f"📷 Photo check unavailable: no usable answer (stop_reason={response.stop_reason})")
            return None

        allowed = set(dish_keywords)
        return PhotoVerdict(
            is_food=answer.is_food,
            shows_meat=answer.is_food and answer.shows_meat,
            dishes=[dish for dish in answer.dishes if dish in allowed] if answer.is_food else [],
            model=getattr(response, "model", None),
        )

    @staticmethod
    def _warn_missing_key_once() -> None:
        global _missing_key_warned
        with _missing_key_lock:
            if _missing_key_warned:
                return
            _missing_key_warned = True
        logger.warning("📷 ANTHROPIC_API_KEY が未設定のため、写真の判定はオフです（本文だけで判定します）")
