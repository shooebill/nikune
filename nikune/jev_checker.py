"""
TypeSafe (Jev) への問い合わせを担う薄い共通モジュール

Jev は文章を生成せず、State と型つきの質問（Noul / Score / Choice）に対して
確率・期待値だけを返す System One モデル。このモジュールは「1回問い合わせて数値を受け取る」
ところだけを担当し、しきい値や判定ルールは呼び出し側（例: nikune/quote_safety.py）が持つ。

設計上の約束:
    - API キー未設定なら機能オフ（status="disabled"）。例外にしない。警告ログはプロセスで1回だけ
    - どんな失敗（タイムアウト・ネットワーク・5xx・認証/課金エラー・レート制限・想定外の応答形式）でも
      例外を呼び出し元に投げず、status="error" の JevResult を返す
    - API キーはログ・例外メッセージ・戻り値に一切含めない
"""

import logging
import math
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Mapping, Optional

from typesafe_sdk import Choice, JSONContent, Noul, RetryPolicy, Score, TypeSafeClient

from config import settings

logger = logging.getLogger(__name__)

# SDK 内部のリトライ（429/5xx/接続エラー/タイムアウト対象）。cron 実行を長く止めないよう
# 1回だけに絞り、リトライ込みの総時間にも上限をかける
DEFAULT_MAX_RETRIES = 1
# エラーメッセージを残す最大文字数（サーバー応答本文が長い場合の保険）
MAX_ERROR_MESSAGE_LENGTH = 200

JevStatus = Literal["ok", "disabled", "error"]
JevQuestion = Noul | Score | Choice


@dataclass(frozen=True)
class JevResult:
    """Jev への問い合わせ結果

    Attributes:
        status: "ok"（判定できた）/ "disabled"（キー未設定で問い合わせていない）/ "error"（判定できなかった）
        nouls: Noul 質問のキー → yes の確率（0〜1）
        scores: Score 質問のキー → 段階の期待値（0 〜 段階数-1）
        model: 実際に応答したモデルのバージョン ID
        error: status="error" のときの理由（API キーは含まない）
    """

    status: JevStatus
    nouls: Dict[str, float] = field(default_factory=dict)
    scores: Dict[str, float] = field(default_factory=dict)
    model: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class JevChecker:
    """Jev に1リクエストで複数の質問を投げ、結果を JevResult で返す"""

    _disabled_warning_logged = False
    _disabled_warning_lock = threading.Lock()

    def __init__(
        self,
        api_key: Optional[str],
        model: str = "jev-1.13.0",
        timeout_seconds: float = 10.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        client: Optional[Any] = None,
    ) -> None:
        """
        Args:
            api_key: TypeSafe の API キー。None/空文字なら機能オフ
            model: モデル ID（バージョン固定推奨）
            timeout_seconds: 1回の HTTP 呼び出しのタイムアウト（秒）
            max_retries: SDK 内部のリトライ回数
            client: テスト用に差し込むクライアント（system_one() を持つオブジェクト）
        """
        self._api_key = (api_key or "").strip() or None
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client = client

    @classmethod
    def from_settings(cls) -> "JevChecker":
        """config/settings.py の値から生成する（呼び出し時点の値を読む）"""
        return cls(
            api_key=settings.TYPESAFE_API_KEY,
            model=settings.TYPESAFE_MODEL,
            timeout_seconds=settings.TYPESAFE_TIMEOUT_SECONDS,
        )

    @property
    def enabled(self) -> bool:
        return self._api_key is not None or self._client is not None

    def __repr__(self) -> str:
        # API キーを repr に出さない
        return f"JevChecker(enabled={self.enabled}, model={self.model!r}, timeout_seconds={self.timeout_seconds})"

    def ask(self, state: JSONContent, questions: Mapping[str, JevQuestion]) -> JevResult:
        """State と質問を Jev に送り、結果を返す。例外は投げない"""
        if not self.enabled:
            self._log_disabled_once()
            return JevResult(status="disabled")

        try:
            client = self._get_client()
            response = client.system_one(state=state, questions=dict(questions), model=self.model)
            return self._parse_response(response, questions)
        except Exception as e:  # noqa: BLE001 - どんな失敗でも呼び出し元を止めない
            error = self._describe_error(e)
            logger.warning(f"⚠️ Jev request failed (judgement unavailable): {error}")
            return JevResult(status="error", error=error)

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = TypeSafeClient(
                api_key=self._api_key,
                model=self.model,
                timeout=self.timeout_seconds,
                retry=RetryPolicy(
                    max_retries=self.max_retries,
                    timeout=self.timeout_seconds * (self.max_retries + 1),
                ),
            )
        return self._client

    def _parse_response(self, response: Any, questions: Mapping[str, JevQuestion]) -> JevResult:
        """応答から数値を取り出す。質問に対応する答えが欠けている・範囲外なら error 扱い"""
        nouls: Dict[str, float] = {}
        scores: Dict[str, float] = {}
        response_nouls = getattr(response, "nouls", None) or {}
        response_scores = getattr(response, "scores", None) or {}

        for key, question in questions.items():
            if isinstance(question, Noul):
                value = _finite_float(getattr(response_nouls.get(key), "noul", None))
                if value is None or not 0.0 <= value <= 1.0:
                    return self._shape_error(f"missing or invalid noul answer: {key}")
                nouls[key] = value
            elif isinstance(question, Score):
                value = _finite_float(getattr(response_scores.get(key), "score", None))
                if value is None:
                    return self._shape_error(f"missing or invalid score answer: {key}")
                scores[key] = value
            # Choice は現状の呼び出し側で使っていないため取り出さない（必要になったら追加する）

        model = getattr(response, "model", None)
        return JevResult(status="ok", nouls=nouls, scores=scores, model=model if isinstance(model, str) else None)

    @staticmethod
    def _shape_error(message: str) -> JevResult:
        logger.warning(f"⚠️ Jev returned an unexpected response shape (judgement unavailable): {message}")
        return JevResult(status="error", error=f"unexpected response: {message}")

    def _describe_error(self, error: BaseException) -> str:
        """ログ・戻り値用のエラー説明。API キーが紛れ込まないよう伏せ字にし、長さも制限する"""
        status = getattr(error, "status", None)
        message = str(error)
        if self._api_key:
            message = message.replace(self._api_key, "***")
        if len(message) > MAX_ERROR_MESSAGE_LENGTH:
            message = message[:MAX_ERROR_MESSAGE_LENGTH] + "…"
        prefix = type(error).__name__ + (f" (HTTP {status})" if isinstance(status, int) else "")
        return f"{prefix}: {message}" if message else prefix

    @classmethod
    def _log_disabled_once(cls) -> None:
        with cls._disabled_warning_lock:
            if cls._disabled_warning_logged:
                return
            cls._disabled_warning_logged = True
        logger.warning("⚠️ TYPESAFE_API_KEY is not set: Jev checks are disabled (continuing without them)")


def _finite_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None
