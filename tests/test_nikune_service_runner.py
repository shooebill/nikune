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
            with mock.patch.object(runner, "requests", dummy_requests):
                manager = runner.build_notification_manager()
                self.assertEqual(len(manager.channels), 0)

                # Should not raise even when no channels are configured
                manager.send("通知なし")

        self.assertEqual(len(dummy_requests.calls), 0)
