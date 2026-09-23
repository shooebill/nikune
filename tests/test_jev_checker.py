"""nikune/jev_checker.py のテスト（実APIは呼ばない。httpx2.MockTransportでHTTP応答を差し替える）"""

import json
import logging
from typing import Any, Callable, Dict
from unittest import TestCase, mock

import httpx2
from typesafe_sdk import Noul, RetryPolicy, Score, TypeSafeClient

from config import settings
from nikune.jev_checker import JevChecker, JevQuestion

FAKE_KEY = "fake-test-key-0123456789"

QUESTIONS: Dict[str, JevQuestion] = {
    "is_food": Noul(instructions="Is `text` about food?"),
    "value": Score(instructions="How interesting is `text`?", criteria=["low", "high"]),
}


def _checker_with_handler(handler: Callable[[httpx2.Request], httpx2.Response]) -> JevChecker:
    client = TypeSafeClient(
        api_key=FAKE_KEY,
        transport=httpx2.MockTransport(handler),
        retry=RetryPolicy(max_retries=0),
    )
    return JevChecker(api_key=FAKE_KEY, client=client)


def _ok_body(noul: Any = 0.9, score: Any = 1.2) -> Dict[str, Any]:
    return {
        "model": "jev-1.13.0",
        "answers": {
            "is_food": {"type": "noul", "noul": noul},
            "value": {
                "type": "score",
                "score": score,
                "legend": {"0": "low", "1": "high"},
                "probabilities": {"0": 0.2, "1": 0.8},
                "confidence": 0.7,
            },
        },
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }


class JevCheckerSuccessTests(TestCase):
    def test_parses_nouls_scores_and_model(self) -> None:
        sent: Dict[str, Any] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            sent.update(json.loads(request.content))
            return httpx2.Response(200, json=_ok_body())

        result = _checker_with_handler(handler).ask({"text": "テスト"}, QUESTIONS)

        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.nouls["is_food"], 0.9)
        self.assertAlmostEqual(result.scores["value"], 1.2)
        self.assertEqual(result.model, "jev-1.13.0")
        # モデルはバージョン固定の既定値が送られる
        self.assertEqual(sent["model"], "jev-1.13.0")


class JevCheckerFailureTests(TestCase):
    """どんな失敗でも例外を投げず status="error" を返す"""

    def _assert_error(self, handler: Callable[[httpx2.Request], httpx2.Response]) -> str:
        with self.assertLogs("nikune.jev_checker", level=logging.WARNING) as logs:
            result = _checker_with_handler(handler).ask({"text": "テスト"}, QUESTIONS)
        self.assertEqual(result.status, "error")
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)
        # APIキーが戻り値にもログにも出ない
        self.assertNotIn(FAKE_KEY, result.error or "")
        self.assertNotIn(FAKE_KEY, "\n".join(logs.output))
        return result.error or ""

    def test_server_error(self) -> None:
        error = self._assert_error(lambda request: httpx2.Response(500, json={"error": "internal"}))
        self.assertIn("500", error)

    def test_authentication_error(self) -> None:
        self._assert_error(lambda request: httpx2.Response(401, json={"error": "invalid key"}))

    def test_billing_disabled_error(self) -> None:
        self._assert_error(lambda request: httpx2.Response(402, json={"error": "billing disabled"}))

    def test_rate_limit_error(self) -> None:
        self._assert_error(lambda request: httpx2.Response(429, json={"error": "slow down"}))

    def test_network_error(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("connection refused")

        self._assert_error(handler)

    def test_timeout(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("timed out")

        self._assert_error(handler)

    def test_unexpected_json_shape(self) -> None:
        self._assert_error(lambda request: httpx2.Response(200, json={"unexpected": True}))

    def test_missing_answer(self) -> None:
        body = _ok_body()
        del body["answers"]["is_food"]
        error = self._assert_error(lambda request: httpx2.Response(200, json=body))
        self.assertIn("is_food", error)

    def test_non_json_body(self) -> None:
        self._assert_error(lambda request: httpx2.Response(200, text="<html>oops</html>"))

    def test_error_message_containing_key_is_redacted(self) -> None:
        client = mock.MagicMock()
        client.system_one.side_effect = RuntimeError(f"boom with {FAKE_KEY} inside")
        checker = JevChecker(api_key=FAKE_KEY, client=client)

        with self.assertLogs("nikune.jev_checker", level=logging.WARNING) as logs:
            result = checker.ask({"text": "テスト"}, QUESTIONS)

        self.assertEqual(result.status, "error")
        self.assertNotIn(FAKE_KEY, result.error or "")
        self.assertNotIn(FAKE_KEY, "\n".join(logs.output))
        self.assertNotIn(FAKE_KEY, repr(checker))


class JevCheckerDisabledTests(TestCase):
    def test_missing_key_is_disabled_without_request(self) -> None:
        checker = JevChecker(api_key=None)
        with mock.patch("nikune.jev_checker.TypeSafeClient") as client_cls:
            result = checker.ask({"text": "テスト"}, QUESTIONS)

        self.assertFalse(checker.enabled)
        self.assertEqual(result.status, "disabled")
        client_cls.assert_not_called()

    def test_blank_key_is_disabled(self) -> None:
        self.assertFalse(JevChecker(api_key="   ").enabled)

    def test_from_settings_reads_current_settings(self) -> None:
        # conftestでTYPESAFE_API_KEYは未設定扱いになっている
        checker = JevChecker.from_settings()
        self.assertFalse(checker.enabled)
        self.assertEqual(checker.model, settings.TYPESAFE_MODEL)
