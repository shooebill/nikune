"""scripts/check_logs.py（ログ確認→異常時のみ通知）のテスト。ログの見本は汎用の文言で作り、実データは使わない"""

import os
import pathlib
import sys
import tempfile
from importlib import import_module
from typing import Any, List, cast
from unittest import TestCase, mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

check_logs = cast(Any, import_module("scripts.check_logs"))

DAY = "2026-09-23"


def _line(clock: str, logger: str, level: str, message: str) -> str:
    return f"{DAY} {clock},123 - {logger} - {level} - {message}"


# 独り言投稿が正常に終わった回（毎回出る既知の WARNING を含む）
POST_OK_0900 = [
    _line("09:00:01", "__main__", "INFO", "🐻 nikune started"),
    _line(
        "09:00:02", "nikune.content_generator", "WARNING", "⚠️ 引用コメントファイルが見つかりませんでした: data/x.tsv"
    ),
    _line(
        "09:00:03",
        "nikune.post_safety",
        "INFO",
        "🧭 Jev pre-post check: route=post_now template=1 decision=OK nouls[a=0.10] persona=checked",
    ),
    _line("09:00:04", "nikune.twitter_client", "INFO", "✅ Tweet posted successfully! ID: 111"),
    _line("09:00:05", "nikune.scheduler", "WARNING", "⚠️ Scheduler is not running"),
    "🎉 Tweet posted successfully!",
    _line("09:00:05", "__main__", "INFO", "✅ Operation completed successfully"),
]

QUOTE_OK_NOTHING_QUOTED = [
    _line("12:30:01", "__main__", "INFO", "🐻 nikune started"),
    _line(
        "12:30:05",
        "nikune.quote_safety",
        "INFO",
        "🧭 Jev quote check: tweet=1 decision=SKIP nouls[a=0.90] value_score=-",
    ),
    _line("12:30:06", "__main__", "INFO", "✅ Quote retweet check completed:"),
    _line("12:30:06", "__main__", "INFO", "   🔄 Quote tweets posted: 0"),
    _line("12:30:06", "__main__", "INFO", "✅ Operation completed successfully"),
]


class CheckLogsTestBase(TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log_path = pathlib.Path(self._tmp.name) / "test.log"
        self.notifier = mock.Mock()
        self.notifier.send.return_value = True

    def write_log(self, lines: List[str]) -> None:
        self.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_check(self, target: str, scheduled: str, *extra: str) -> int:
        argv = [target, scheduled, "--date", DAY, "--log-file", str(self.log_path), *extra]
        with mock.patch.object(check_logs, "load_dotenv"), mock.patch("builtins.print"):
            return cast(int, check_logs.main(argv, notifier_factory=lambda: self.notifier))

    def sent_message(self) -> str:
        self.notifier.send.assert_called_once()
        return cast(str, self.notifier.send.call_args.args[0])


class NoNotificationTests(CheckLogsTestBase):
    def test_successful_post_with_known_warnings_is_not_notified(self) -> None:
        self.write_log(POST_OK_0900)
        self.assertEqual(self.run_check("post", "09:00"), 0)
        self.notifier.send.assert_not_called()

    def test_quote_with_skip_and_zero_quotes_is_not_notified(self) -> None:
        self.write_log(QUOTE_OK_NOTHING_QUOTED)
        self.assertEqual(self.run_check("quote", "12:30"), 0)
        self.notifier.send.assert_not_called()

    def test_rate_limited_quote_run_counts_as_success(self) -> None:
        self.write_log(
            [
                _line("12:30:01", "__main__", "INFO", "⏰ Quote tweets temporarily limited"),
                _line("12:30:01", "__main__", "INFO", "✅ Operation completed successfully"),
            ]
        )
        self.assertEqual(self.run_check("quote", "12:30"), 0)
        self.notifier.send.assert_not_called()

    def test_errors_of_previous_run_are_not_picked_up(self) -> None:
        previous_failed_run = [
            _line("09:00:01", "__main__", "INFO", "🐻 nikune started"),
            _line("09:00:02", "__main__", "ERROR", "❌ Operation failed"),
            "Traceback (most recent call last):",
            "RuntimeError: previous run",
        ]
        current_ok_run = [line.replace(" 09:00:", " 15:00:") for line in POST_OK_0900 if line.startswith(DAY)]
        self.write_log(previous_failed_run + current_ok_run)
        self.assertEqual(self.run_check("post", "15:00"), 0)
        self.notifier.send.assert_not_called()

    def test_next_run_outside_window_is_ignored(self) -> None:
        later_failed_run = [_line("15:00:02", "__main__", "ERROR", "❌ Operation failed")]
        self.write_log(POST_OK_0900 + later_failed_run)
        self.assertEqual(self.run_check("post", "09:00"), 0)
        self.notifier.send.assert_not_called()


class NotificationTests(CheckLogsTestBase):
    def test_missing_success_record_is_notified(self) -> None:
        self.write_log([_line("09:00:01", "__main__", "INFO", "🐻 nikune started")])
        self.assertEqual(self.run_check("post", "09:00"), 1)
        message = self.sent_message()
        self.assertIn("[nikune] 09:00 の投稿: 成功の記録がありません", message)
        self.assertIn("host:", message)

    def test_run_that_never_logged_is_notified_with_file_tail(self) -> None:
        # 起動時に落ちた（ログ設定前の Traceback にはタイムスタンプがない）→ 前の回の続きに見える
        self.write_log(
            POST_OK_0900 + ["Traceback (most recent call last):", "ModuleNotFoundError: No module named 'x'"]
        )
        self.assertEqual(self.run_check("post", "15:00"), 1)
        message = self.sent_message()
        self.assertIn("成功の記録がありません", message)
        self.assertIn("ModuleNotFoundError", message)

    def test_missing_log_file_is_notified(self) -> None:
        self.assertEqual(self.run_check("post", "09:00"), 1)
        self.assertIn("ログファイルがありません", self.sent_message())

    def test_error_level_line_is_notified_even_if_posted(self) -> None:
        self.write_log(POST_OK_0900 + [_line("09:00:06", "nikune.database", "ERROR", "something broke")])
        self.assertEqual(self.run_check("post", "09:00"), 1)
        message = self.sent_message()
        self.assertIn("失敗の記録があります", message)
        self.assertNotIn("成功の記録がありません", message)
        self.assertIn("something broke", message)

    def test_traceback_is_notified(self) -> None:
        self.write_log(POST_OK_0900 + ["Traceback (most recent call last):", "ValueError: boom"])
        self.assertEqual(self.run_check("post", "09:00"), 1)
        self.assertIn("失敗の記録があります", self.sent_message())

    def test_failed_quote_check_is_notified(self) -> None:
        self.write_log(
            [
                _line("12:30:01", "__main__", "ERROR", "❌ Quote retweet check failed: api down"),
                _line("12:30:01", "__main__", "ERROR", "❌ Operation failed"),
            ]
        )
        self.assertEqual(self.run_check("quote", "12:30"), 1)
        message = self.sent_message()
        self.assertIn("12:30 の引用RT", message)
        self.assertIn("成功の記録がありません", message)
        self.assertIn("失敗の記録があります", message)

    def test_post_unchecked_is_notified(self) -> None:
        jev = "🧭 Jev pre-post check: route=post_now template=1 decision=UNCHECKED nouls[-] error=Timeout"
        self.write_log(POST_OK_0900 + [_line("09:00:03", "nikune.post_safety", "WARNING", jev)])
        self.assertEqual(self.run_check("post", "09:00"), 1)
        self.assertIn("TypeSafe でチェックできませんでした", self.sent_message())

    def test_post_warn_is_notified(self) -> None:
        jev = "🧭 Jev pre-post check: route=post_now template=1 decision=WARN nouls[a=0.60] action=posting anyway"
        self.write_log(POST_OK_0900 + [_line("09:00:03", "nikune.post_safety", "WARNING", jev)])
        self.assertEqual(self.run_check("post", "09:00"), 1)
        self.assertIn("Jev の警告があります", self.sent_message())

    def test_post_disabled_is_notified_as_missing_key(self) -> None:
        jev = "🧭 Jev pre-post check: route=post_now template=1 decision=DISABLED nouls[-]"
        self.write_log(POST_OK_0900 + [_line("09:00:03", "nikune.post_safety", "INFO", jev)])
        self.assertEqual(self.run_check("post", "09:00"), 1)
        self.assertIn("TypeSafe のキーが設定されていません", self.sent_message())

    def test_quote_unavailable_is_notified(self) -> None:
        jev = "🧭 Jev quote check: tweet=1 decision=UNAVAILABLE nouls[-] value_score=- error=HTTP 500"
        self.write_log(QUOTE_OK_NOTHING_QUOTED + [_line("12:30:05", "nikune.quote_safety", "INFO", jev)])
        self.assertEqual(self.run_check("quote", "12:30"), 1)
        self.assertIn("TypeSafe でチェックできませんでした", self.sent_message())

    def test_dry_run_does_not_send(self) -> None:
        self.write_log([])
        self.assertEqual(self.run_check("post", "09:00", "--dry-run"), 1)
        self.notifier.send.assert_not_called()

    def test_script_failure_itself_is_notified(self) -> None:
        self.write_log(POST_OK_0900)
        with mock.patch.object(check_logs, "check_log", side_effect=RuntimeError("unexpected")):
            self.assertEqual(self.run_check("post", "09:00"), 2)
        self.assertIn("ログ確認スクリプト自体が失敗しました", self.sent_message())


class SecretMaskingTests(CheckLogsTestBase):
    def test_secrets_in_log_lines_are_masked(self) -> None:
        webhook = "https://hooks.slack.com/services/T000/B000/abcdefghijklmnop"
        self.write_log(
            [
                _line("09:00:01", "x", "ERROR", f"post failed url={webhook}"),
                _line("09:00:02", "x", "ERROR", "header Authorization: Bearer abc.def.ghi"),
                _line("09:00:03", "x", "ERROR", "request api_key=sk-dummy-0123456789 token=tok-dummy-0123"),
                _line("09:00:04", "x", "ERROR", "env value dummy-env-secret-value leaked"),
            ]
        )
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "dummy-env-secret-value"}):
            self.assertEqual(self.run_check("post", "09:00"), 1)
        message = self.sent_message()
        for secret in (webhook, "abcdefghijklmnop", "abc.def.ghi", "sk-dummy-0123456789", "tok-dummy-0123"):
            self.assertNotIn(secret, message)
        self.assertNotIn("dummy-env-secret-value", message)
        self.assertIn("***", message)

    def test_message_lines_are_limited(self) -> None:
        self.write_log([_line("09:00:01", "x", "ERROR", f"error {i} " + "y" * 1000) for i in range(20)])
        self.assertEqual(self.run_check("post", "09:00"), 1)
        message = self.sent_message()
        self.assertNotIn("error 0 ", message)
        self.assertIn("error 19 ", message)
        self.assertLess(len(message), check_logs.MAX_LINES_IN_MESSAGE * (check_logs.MAX_LINE_LENGTH + 1) + 500)
