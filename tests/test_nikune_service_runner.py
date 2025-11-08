import os
import pathlib
import sys
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


class DummyResponse:
    def raise_for_status(self) -> None:
        return None


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
            "LINE_TARGET_IDS": "U123, U456",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(runner, "requests_module", dummy_requests):
                manager = runner.build_notification_manager()

                self.assertEqual(len(manager.channels), 2)

                manager.send("テスト通知")

        self.assertEqual(len(dummy_requests.calls), 3)

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

        line_call_targets = [call["json"]["to"] for call in dummy_requests.calls[1:]]
        self.assertEqual(line_call_targets, ["U123", "U456"])

        for call in dummy_requests.calls[1:]:
            self.assertEqual(
                call["headers"],
                {
                    "Authorization": f"Bearer {env['LINE_CHANNEL_ACCESS_TOKEN']}",
                    "Content-Type": "application/json",
                },
            )
            self.assertEqual(
                call["json"]["messages"][0],
                {"type": "text", "text": "テスト通知"},
            )
            self.assertEqual(call["timeout"], 5)

    def test_notification_manager_without_channels(self) -> None:
        dummy_requests = DummyRequests()

        with mock.patch.dict(os.environ, {}, clear=True):
            manager = runner.build_notification_manager()
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
            with mock.patch.object(runner, "requests_module", dummy_requests):
                manager = runner.build_notification_manager()

                self.assertEqual(len(manager.channels), 1)
                manager.send("Slack通知のみ")

        self.assertEqual(len(dummy_requests.calls), 1)
        call = dummy_requests.calls[0]
        self.assertEqual(call["url"], env["SLACK_WEBHOOK_URL"])
        self.assertEqual(call["json"], {"text": "Slack通知のみ"})
        self.assertIsNone(call["headers"])
        self.assertEqual(call["timeout"], 5)

    def test_notification_manager_line_only_trims_targets(self) -> None:
        dummy_requests = DummyRequests()
        env = {
            "LINE_CHANNEL_ACCESS_TOKEN": "token-xyz",
            "LINE_TARGET_IDS": " U123 , ,U456,",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(runner, "requests_module", dummy_requests):
                manager = runner.build_notification_manager()

                self.assertEqual(len(manager.channels), 1)
                manager.send("LINE通知のみ")

        # Two valid target IDs should result in two calls
        self.assertEqual(len(dummy_requests.calls), 2)

        for call, target in zip(dummy_requests.calls, ["U123", "U456"]):
            self.assertEqual(
                call["headers"],
                {
                    "Authorization": f"Bearer {env['LINE_CHANNEL_ACCESS_TOKEN']}",
                    "Content-Type": "application/json",
                },
            )
            self.assertEqual(call["timeout"], 5)
            self.assertEqual(call["json"]["to"], target)
            self.assertEqual(
                call["json"]["messages"][0],
                {"type": "text", "text": "LINE通知のみ"},
            )

    def test_line_notification_requires_targets(self) -> None:
        env = {
            "LINE_CHANNEL_ACCESS_TOKEN": "token-xyz",
            "LINE_TARGET_IDS": "   , ,",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            manager = runner.build_notification_manager()

        self.assertEqual(len(manager.channels), 0)

    def test_notification_manager_continues_after_channel_error(self) -> None:
        failing_channel = mock.Mock()
        failing_channel.name = "FailingChannel"
        failing_channel.send = mock.Mock(side_effect=RuntimeError("boom"))

        succeeding_channel = mock.Mock()
        succeeding_channel.name = "SucceedingChannel"
        succeeding_channel.send = mock.Mock()

        manager = runner.NotificationManager([failing_channel, succeeding_channel])

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
