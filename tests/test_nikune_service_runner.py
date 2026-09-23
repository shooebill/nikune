import os
import pathlib
import signal
import subprocess
import sys
import tempfile
from importlib import import_module
from typing import Any, cast
from unittest import TestCase, mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

runner = cast(
    Any,
    import_module("scripts.nikune_service_runner"),
)
# 通知の部品は nikune/notifications.py に移した（見張り役はそれを import して使う）
notifications = cast(Any, import_module("nikune.notifications"))


class DummyResponse:
    def raise_for_status(self) -> None:
        return None


class FailingDummyRequests:
    """通信が常に失敗するダミーのrequestsモジュール代替（通知の全滅を再現する）。"""

    def post(
        self,
        url: str,
        json: Any | None = None,
        headers: dict[str, Any] | None = None,
        timeout: float | int | None = None,
    ) -> DummyResponse:
        raise ConnectionError("simulated network failure")


class DummyRequests:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        json: Any | None = None,
        headers: dict[str, Any] | None = None,
        timeout: float | int | None = None,
    ) -> DummyResponse:
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return DummyResponse()


class NotificationManagerTests(TestCase):
    def test_notification_manager_sends_to_all_channels(self) -> None:
        dummy_requests = DummyRequests()
        env = {
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/test",
            "SLACK_WEBHOOK_USERNAME": "nikune-bot",
            "SLACK_WEBHOOK_ICON_EMOJI": ":bear:",
            "LINE_CHANNEL_ACCESS_TOKEN": "token-123",
            "LINE_NOTIFY_ENABLED": "true",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(notifications, "requests_module", dummy_requests):
                manager = notifications.build_notification_manager()

                self.assertEqual(len(manager.channels), 2)

                manager.send("テスト通知")

        self.assertEqual(len(dummy_requests.calls), 2)

        slack_call = dummy_requests.calls[0]
        self.assertEqual(slack_call["url"], env["SLACK_WEBHOOK_URL"])
        self.assertEqual(
            slack_call["json"],
            {
                "text": "テスト通知",
                "username": env["SLACK_WEBHOOK_USERNAME"],
                "icon_emoji": env["SLACK_WEBHOOK_ICON_EMOJI"],
            },
        )
        self.assertEqual(slack_call["headers"], None)
        self.assertEqual(slack_call["timeout"], 5)

        line_call = dummy_requests.calls[1]
        self.assertEqual(line_call["url"], "https://api.line.me/v2/bot/message/broadcast")
        self.assertEqual(
            line_call["headers"],
            {
                "Authorization": f"Bearer {env['LINE_CHANNEL_ACCESS_TOKEN']}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(
            line_call["json"],
            {"messages": [{"type": "text", "text": "テスト通知"}]},
        )
        self.assertEqual(line_call["timeout"], 5)

    def test_notification_manager_without_channels(self) -> None:
        dummy_requests = DummyRequests()

        with mock.patch.dict(os.environ, {}, clear=True):
            manager = notifications.build_notification_manager()
            self.assertEqual(len(manager.channels), 0)

            # Should not raise even when no channels are configured
            manager.send("通知なし")

        self.assertEqual(len(dummy_requests.calls), 0)

    def test_notification_manager_slack_only(self) -> None:
        dummy_requests = DummyRequests()
        env = {
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/slack-only",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(notifications, "requests_module", dummy_requests):
                manager = notifications.build_notification_manager()

                self.assertEqual(len(manager.channels), 1)
                manager.send("Slack通知のみ")

        self.assertEqual(len(dummy_requests.calls), 1)
        call = dummy_requests.calls[0]
        self.assertEqual(call["url"], env["SLACK_WEBHOOK_URL"])
        self.assertEqual(call["json"], {"text": "Slack通知のみ"})
        self.assertIsNone(call["headers"])
        self.assertEqual(call["timeout"], 5)

    def test_notification_manager_line_only_broadcasts(self) -> None:
        dummy_requests = DummyRequests()
        env = {
            "LINE_CHANNEL_ACCESS_TOKEN": "token-xyz",
            "LINE_NOTIFY_ENABLED": "true",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(notifications, "requests_module", dummy_requests):
                manager = notifications.build_notification_manager()

                self.assertEqual(len(manager.channels), 1)
                manager.send("LINE通知のみ")

        # broadcastは宛先指定なしの1回呼び出しになる
        self.assertEqual(len(dummy_requests.calls), 1)

        call = dummy_requests.calls[0]
        self.assertEqual(call["url"], "https://api.line.me/v2/bot/message/broadcast")
        self.assertEqual(
            call["headers"],
            {
                "Authorization": f"Bearer {env['LINE_CHANNEL_ACCESS_TOKEN']}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(call["timeout"], 5)
        self.assertNotIn("to", call["json"])
        self.assertEqual(
            call["json"]["messages"][0],
            {"type": "text", "text": "LINE通知のみ"},
        )

    def test_line_notification_disabled_by_default(self) -> None:
        env = {
            "LINE_CHANNEL_ACCESS_TOKEN": "token-xyz",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            manager = notifications.build_notification_manager()

        self.assertEqual(len(manager.channels), 0)

    def test_line_notification_requires_token_even_when_enabled(self) -> None:
        env = {
            "LINE_NOTIFY_ENABLED": "true",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            manager = notifications.build_notification_manager()

        self.assertEqual(len(manager.channels), 0)

    def test_notification_manager_continues_after_channel_error(self) -> None:
        failing_channel = mock.Mock()
        failing_channel.name = "FailingChannel"
        failing_channel.send = mock.Mock(side_effect=RuntimeError("boom"))

        succeeding_channel = mock.Mock()
        succeeding_channel.name = "SucceedingChannel"
        succeeding_channel.send = mock.Mock()

        manager = notifications.NotificationManager([failing_channel, succeeding_channel])

        # Should not raise even if one channel fails
        manager.send("複数チャネル通知")

        failing_channel.send.assert_called_once_with("複数チャネル通知")
        succeeding_channel.send.assert_called_once_with("複数チャネル通知")


class UtilityFunctionsTests(TestCase):
    def test_parse_command_with_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            result = runner._parse_command(["python", "default.py"])
            self.assertEqual(result, ["python", "default.py"])

    def test_parse_command_with_env_override(self) -> None:
        with mock.patch.dict(os.environ, {"NIKUNE_SERVICE_COMMAND": "python custom.py --flag"}, clear=True):
            result = runner._parse_command(["python", "default.py"])
            self.assertEqual(result, ["python", "custom.py", "--flag"])

    def test_parse_command_with_quotes(self) -> None:
        with mock.patch.dict(os.environ, {"NIKUNE_SERVICE_COMMAND": 'python "file with spaces.py"'}, clear=True):
            result = runner._parse_command(["python", "default.py"])
            self.assertEqual(result, ["python", "file with spaces.py"])

    def test_env_flag_default_false(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(runner._env_flag("TEST_FLAG"))

    def test_env_flag_default_true(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(runner._env_flag("TEST_FLAG", default=True))

    def test_env_flag_true_values(self) -> None:
        for value in ["1", "true", "True", "TRUE", "t", "T", "yes", "YES", "y", "Y"]:
            with mock.patch.dict(os.environ, {"TEST_FLAG": value}, clear=True):
                self.assertTrue(runner._env_flag("TEST_FLAG"), f"Failed for value: {value}")

    def test_env_flag_false_values(self) -> None:
        for value in ["0", "false", "False", "FALSE", "no", "NO", "n", "N", "other"]:
            with mock.patch.dict(os.environ, {"TEST_FLAG": value}, clear=True):
                self.assertFalse(runner._env_flag("TEST_FLAG"), f"Failed for value: {value}")


class NotificationManagerEscalationTests(TestCase):
    """
    過去に発生したバグ:
      通知チャネル（Slack/LINE）の実装は例外を自分で握りつぶしてログを
      出すだけで、送信の成否をNotificationManagerに一切伝えていなかった。
      そのため「再起動上限超過」のようなCRITICALアラートを含め、全チャネルの
      送信が失敗しても、NotificationManager側ではそれを一切検知できず、
      Webhook失効やトークン期限切れでボットが停止していることに誰も
      気づけなくなる恐れがあった。

      このテストでは、channel.send()がbool（成否）を返すよう変更した結果、
      NotificationManager.send()が全滅を検知してERRORログを残し、
      ローカルのマーカーファイルに書き込むことを確認する。
    """

    def test_send_returns_true_when_at_least_one_channel_succeeds(self) -> None:
        dummy_requests = DummyRequests()
        env = {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/ok"}

        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(notifications, "requests_module", dummy_requests):
                manager = notifications.build_notification_manager()
                result = manager.send("正常系の通知")

        self.assertTrue(result)

    def test_send_returns_false_and_logs_aggregate_error_when_all_channels_fail(self) -> None:
        failing_requests = FailingDummyRequests()

        with tempfile.TemporaryDirectory() as tmp_dir:
            # 実際のlogs/配下を汚さないよう、マーカーファイルの出力先をテスト用に退避する
            marker_path = pathlib.Path(tmp_dir) / "notification_failure.marker"
            env = {
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/broken",
                "LINE_CHANNEL_ACCESS_TOKEN": "expired-token",
                "LINE_NOTIFY_ENABLED": "true",
                "NIKUNE_NOTIFICATION_FAILURE_MARKER": str(marker_path),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(notifications, "requests_module", failing_requests):
                    manager = notifications.build_notification_manager()
                    with self.assertLogs(notifications.LOGGER, level="ERROR") as log_ctx:
                        result = manager.send("[CRITICAL] テスト用の重大アラート")

        self.assertFalse(result)
        self.assertTrue(
            any("全ての通知チャネル" in message for message in log_ctx.output),
            msg=f"全滅時の集約エラーログが見つかりません: {log_ctx.output}",
        )

    def test_send_writes_marker_file_when_all_configured_channels_fail(self) -> None:
        failing_requests = FailingDummyRequests()

        with tempfile.TemporaryDirectory() as tmp_dir:
            marker_path = pathlib.Path(tmp_dir) / "notification_failure.marker"
            env = {
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/broken",
                "NIKUNE_NOTIFICATION_FAILURE_MARKER": str(marker_path),
            }

            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(notifications, "requests_module", failing_requests):
                    manager = notifications.build_notification_manager()
                    manager.send("[CRITICAL] 通知経路が死んでいるテスト")

            self.assertTrue(marker_path.exists())
            content = marker_path.read_text(encoding="utf-8")
            self.assertIn("[CRITICAL] 通知経路が死んでいるテスト", content)

    def test_send_does_not_write_marker_when_no_channels_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            marker_path = pathlib.Path(tmp_dir) / "notification_failure.marker"
            env = {"NIKUNE_NOTIFICATION_FAILURE_MARKER": str(marker_path)}

            with mock.patch.dict(os.environ, env, clear=True):
                manager = notifications.build_notification_manager()
                result = manager.send("通知チャネル未設定時のテスト")

            self.assertFalse(result)
            self.assertFalse(marker_path.exists())


class RunnerStateTests(TestCase):
    def test_request_stop_sets_should_stop_flag(self) -> None:
        state = runner._RunnerState()
        self.assertFalse(state.should_stop)

        state.request_stop(15)

        self.assertTrue(state.should_stop)


class WaitForChildProcessTests(TestCase):
    """
    過去に発生したバグ:
      SIGTERM/SIGINTのカスタムハンドラが`should_stop`フラグを立てるだけの
      実装だったため、`process.wait()`を無条件・無期限にブロックしていた
      旧実装では、シグナル受信後も子プロセスの自然な終了を待ち続けてしまい、
      運用者がしびれを切らしてSIGKILLすると、待機中だった子プロセス
      （`--schedule`のスケジューラー）が孤児化する可能性があった。

      ここでは実際のOSシグナルは発火させず、モックプロセスと
      `_RunnerState`フラグの操作だけで同じ状況を再現し、
      `_wait_for_child_process`がterminate()/kill()を能動的に呼び出して
      確実にクリーンアップすることを確認する。
    """

    def test_returns_immediately_when_process_exits_before_shutdown_requested(self) -> None:
        state = runner._RunnerState()
        process = mock.Mock()
        process.pid = 1234
        process.wait.return_value = 0

        return_code = runner._wait_for_child_process(process, state, poll_interval=0.01)

        self.assertEqual(return_code, 0)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_terminates_child_process_when_shutdown_requested_mid_poll(self) -> None:
        state = runner._RunnerState()
        process = mock.Mock()
        process.pid = 4321

        # ポーリング中にシグナルが届いた状況を模す（stateフラグを直接立てる）。
        # terminate()送信後、子プロセスが速やかに終了した想定で2回目のwait()が成功する。
        process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="dummy", timeout=0.01),
            -15,
        ]

        state.request_stop(signal.SIGTERM)

        return_code = runner._wait_for_child_process(process, state, poll_interval=0.01)

        self.assertEqual(return_code, -15)
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    def test_kills_child_process_after_grace_period_expires(self) -> None:
        state = runner._RunnerState()
        state.should_stop = True
        process = mock.Mock()
        process.pid = 999

        process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="dummy", timeout=0.01),
            subprocess.TimeoutExpired(cmd="dummy", timeout=0.01),
            subprocess.TimeoutExpired(cmd="dummy", timeout=0.01),
            -9,
        ]

        # 1回目: terminate_requested_atの記録。2回目: 猶予期間内（超過なし）。
        # 3回目: 猶予期間超過 -> kill()。
        time_values = [1000.0, 1001.0, 1010.0]

        with mock.patch.object(runner.time, "time", side_effect=time_values):
            return_code = runner._wait_for_child_process(process, state, poll_interval=0.01, grace_period=5.0)

        self.assertEqual(return_code, -9)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
