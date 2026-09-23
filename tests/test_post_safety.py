"""nikune/post_safety.py（投稿直前チェック）のテスト（実APIは呼ばない。JevChecker.ask を差し替える）"""

import os
import tempfile
from typing import List, Mapping, Optional, Tuple
from unittest import TestCase, mock

from typesafe_sdk import JSONContent

from nikune import post_safety
from nikune.jev_checker import JevChecker, JevQuestion, JevResult
from nikune.post_safety import (
    OFFENSIVE_KEY,
    PERSONA_KEY,
    PROMOTION_KEY,
    PostSafetyVerdict,
    evaluate_post,
    load_persona,
    should_post,
)

MISSING_PERSONA = "/nonexistent/persona.tsv"


class StubChecker(JevChecker):
    """ask() の戻り値（または例外）を固定し、呼び出し内容を記録するテスト用チェッカー"""

    def __init__(self, result: Optional[JevResult] = None, error: Optional[Exception] = None) -> None:
        super().__init__(api_key="fake-test-key")
        self.result = result
        self.error = error
        self.calls: List[Tuple[JSONContent, Mapping[str, JevQuestion]]] = []

    def ask(self, state: JSONContent, questions: Mapping[str, JevQuestion]) -> JevResult:
        self.calls.append((state, questions))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def ok_result(**nouls: float) -> JevResult:
    values = {PROMOTION_KEY: 0.02, OFFENSIVE_KEY: 0.03}
    values.update(nouls)
    return JevResult(status="ok", nouls=values, model="jev-1.13.0")


def _write_persona(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".tsv")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return path


class PersonaLoadingTests(TestCase):
    def test_missing_file_returns_none(self) -> None:
        self.assertIsNone(load_persona(MISSING_PERSONA))

    def test_reads_crlf_tsv_with_header(self) -> None:
        path = _write_persona("分類\t項目\t内容\t補足\r\nテスト分類\tテスト項目\tテスト内容\t\r\nA\tB\tC\tD\r\n")
        self.addCleanup(os.remove, path)

        rows = load_persona(path)

        self.assertEqual(
            rows,
            [
                {"category": "テスト分類", "item": "テスト項目", "content": "テスト内容"},
                {"category": "A", "item": "B", "content": "C", "note": "D"},
            ],
        )

    def test_unexpected_header_returns_none(self) -> None:
        path = _write_persona("a\tb\tc\r\n1\t2\t3\r\n")
        self.addCleanup(os.remove, path)
        with self.assertLogs("nikune.post_safety", level="WARNING"):
            self.assertIsNone(load_persona(path))


class PersonaQuestionTests(TestCase):
    def test_persona_question_is_skipped_without_persona_file(self) -> None:
        checker = StubChecker(ok_result())

        verdict = evaluate_post(checker, "テスト", route="post_now", persona_path=MISSING_PERSONA)

        state, questions = checker.calls[0]
        self.assertNotIn(PERSONA_KEY, questions)
        self.assertEqual(set(questions), {PROMOTION_KEY, OFFENSIVE_KEY})
        assert isinstance(state, dict)
        self.assertNotIn("persona", state)
        self.assertFalse(verdict.persona_checked)
        self.assertEqual(verdict.decision, "ok")

    def test_persona_question_is_asked_with_persona_file(self) -> None:
        path = _write_persona("分類\t項目\t内容\t補足\r\nテスト分類\tテスト項目\tテスト内容\t\r\n")
        self.addCleanup(os.remove, path)
        checker = StubChecker(ok_result(**{PERSONA_KEY: 0.95}))

        verdict = evaluate_post(checker, "テスト", route="post_now", persona_path=path)

        state, questions = checker.calls[0]
        self.assertIn(PERSONA_KEY, questions)
        assert isinstance(state, dict)
        self.assertEqual(state["persona"], [{"category": "テスト分類", "item": "テスト項目", "content": "テスト内容"}])
        self.assertEqual(state["post"], {"text": "テスト"})
        self.assertTrue(verdict.persona_checked)
        self.assertEqual(verdict.decision, "ok")


class DecisionTests(TestCase):
    def _evaluate(self, checker: JevChecker) -> PostSafetyVerdict:
        return evaluate_post(checker, "テスト本文", route="scheduled", template_id=7, persona_path=MISSING_PERSONA)

    def test_ok_logs_info_line_without_post_text(self) -> None:
        with self.assertLogs("nikune.post_safety", level="INFO") as captured:
            verdict = self._evaluate(StubChecker(ok_result()))
        self.assertEqual(verdict.decision, "ok")
        self.assertTrue(should_post(verdict))
        line = captured.output[-1]
        self.assertIn("route=scheduled", line)
        self.assertIn("template=7", line)
        self.assertIn("decision=OK", line)
        self.assertIn(f"{PROMOTION_KEY}=0.02", line)
        self.assertNotIn("テスト本文", line)

    def test_ng_judgement_warns_but_still_posts(self) -> None:
        with self.assertLogs("nikune.post_safety", level="WARNING") as captured:
            verdict = self._evaluate(StubChecker(ok_result(**{PROMOTION_KEY: 0.95})))
        self.assertEqual(verdict.decision, "warn")
        self.assertTrue(verdict.would_block)
        self.assertTrue(should_post(verdict))  # 警告のみ
        self.assertIn("decision=WARN", captured.output[-1])
        self.assertIn("warn-only", captured.output[-1])

    def test_low_persona_consistency_warns(self) -> None:
        verdict = post_safety.decide({PERSONA_KEY: 0.1, PROMOTION_KEY: 0.0, OFFENSIVE_KEY: 0.0})
        self.assertEqual(verdict, [f"{PERSONA_KEY}<{post_safety.PERSONA_CONSISTENT_THRESHOLD}"])

    def test_uncertain_band_warns(self) -> None:
        # 0.5 付近（quote_safety と同じあいまい帯）は「わからない」として警告理由に入る
        reasons = post_safety.decide({PERSONA_KEY: 0.55, PROMOTION_KEY: 0.02, OFFENSIVE_KEY: 0.02})
        self.assertIn(f"{PERSONA_KEY}~0.5(uncertain)", reasons)
        self.assertEqual(post_safety.decide({PERSONA_KEY: 0.9, PROMOTION_KEY: 0.02, OFFENSIVE_KEY: 0.02}), [])

    def test_api_failure_is_unchecked_and_still_posts(self) -> None:
        checker = StubChecker(JevResult(status="error", error="APIConnectionError: boom"))
        with self.assertLogs("nikune.post_safety", level="WARNING") as captured:
            verdict = self._evaluate(checker)
        self.assertEqual(verdict.decision, "unchecked")
        self.assertTrue(should_post(verdict))
        self.assertIn("decision=UNCHECKED", captured.output[-1])
        self.assertIn("posting without the check", captured.output[-1])

    def test_unexpected_exception_is_unchecked_and_not_raised(self) -> None:
        with self.assertLogs("nikune.post_safety", level="WARNING"):
            verdict = self._evaluate(StubChecker(error=RuntimeError("boom")))
        self.assertEqual(verdict.decision, "unchecked")
        self.assertTrue(should_post(verdict))

    def test_disabled_without_api_key(self) -> None:
        checker = JevChecker(api_key=None)
        with mock.patch("nikune.jev_checker.TypeSafeClient") as client_cls:
            verdict = self._evaluate(checker)
        client_cls.assert_not_called()
        self.assertEqual(verdict.decision, "disabled")
        self.assertTrue(should_post(verdict))

    def test_block_switch_is_separate_from_judgement(self) -> None:
        warn = PostSafetyVerdict(decision="warn", reasons=["x"])
        unchecked = PostSafetyVerdict(decision="unchecked")
        with mock.patch.object(post_safety, "BLOCK_ON_WARN", True):
            self.assertFalse(should_post(warn))
            self.assertTrue(should_post(unchecked))
        with mock.patch.object(post_safety, "BLOCK_ON_UNCHECKED", True):
            self.assertTrue(should_post(warn))
            self.assertFalse(should_post(unchecked))
