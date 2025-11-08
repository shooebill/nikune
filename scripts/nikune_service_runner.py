#!/usr/bin/env python3
"""
nikune service runner
=====================

このスクリプトは `nikune` プロジェクトのスケジューラーを常駐プロセスとして起動し、
異常終了時に自動で再起動させるためのラッパーです。Slack Webhook や LINE Messaging API を
設定すれば障害発生時に通知も送信できます。

基本的な使い方:

    $ python scripts/nikune_service_runner.py

主な環境変数:
    - NIKUNE_SERVICE_COMMAND:
        再起動対象のコマンド（既定: "<python> main.py --schedule"）
    - NIKUNE_RESTART_DELAY:
        再起動までの待機秒数（既定: 5）
    - NIKUNE_RESTART_ON_SUCCESS:
        正常終了時も再起動するか（true/false, 既定: false）
    - NIKUNE_MAX_RESTARTS:
        最大再起動回数（未設定なら無制限）
    - NIKUNE_NOTIFICATION_TIMEOUT:
        通知送信時のタイムアウト秒数（既定: 5）
    - SLACK_WEBHOOK_URL:
        Slack 通知用 Incoming Webhook URL（任意）
    - SLACK_WEBHOOK_USERNAME / SLACK_WEBHOOK_ICON_EMOJI:
        Slack 通知のユーザー名・アイコン（任意）
    - LINE_CHANNEL_ACCESS_TOKEN:
        LINE Messaging API のチャネルアクセストークン（任意）
    - LINE_TARGET_IDS:
        通知を送る LINE の userId / groupId のカンマ区切りリスト（任意）
"""

from __future__ import annotations

import importlib
import logging
import os
import platform
import shlex
import signal
import socket
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from types import ModuleType
from typing import Iterable, List, Optional, Sequence

requests_module: Optional[ModuleType]
try:
    requests_module = importlib.import_module("requests")
except ImportError:
    requests_module = None

LOGGER = logging.getLogger("nikune.service_runner")

# 通知送信時のタイムアウト秒数（環境変数で上書き可能）
try:
    NOTIFICATION_TIMEOUT = int(os.getenv("NIKUNE_NOTIFICATION_TIMEOUT", "5"))
except (TypeError, ValueError):
    NOTIFICATION_TIMEOUT = 5


def _parse_command(default: Sequence[str]) -> List[str]:
    """環境変数からコマンドを取得し、未設定なら既定値を返す。"""
    raw_command = os.getenv("NIKUNE_SERVICE_COMMAND")
    if not raw_command:
        return list(default)

    try:
        return shlex.split(raw_command)
    except ValueError as exc:  # pragma: no cover - 想定外の入力
        LOGGER.warning("Invalid NIKUNE_SERVICE_COMMAND (%s); using default.", exc)
        return list(default)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "t", "yes", "y"}


class NotificationChannel(ABC):
    """通知チャネルの共通インターフェース。"""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def send(self, message: str) -> None:
        """通知を送信する。"""


class SlackNotification(NotificationChannel):
    """Slack Incoming Webhook を利用した通知チャネル。"""

    def __init__(
        self,
        webhook_url: str,
        username: Optional[str] = None,
        icon_emoji: Optional[str] = None,
    ) -> None:
        super().__init__("Slack")
        self.webhook_url = webhook_url
        self.username = username
        self.icon_emoji = icon_emoji

    @classmethod
    def from_env(cls) -> Optional["SlackNotification"]:
        webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        if not webhook_url:
            return None
        if requests_module is None:
            LOGGER.warning("requests が利用できないため Slack 通知は無効化されます。")
            return None

        return cls(
            webhook_url=webhook_url,
            username=os.getenv("SLACK_WEBHOOK_USERNAME"),
            icon_emoji=os.getenv("SLACK_WEBHOOK_ICON_EMOJI"),
        )

    def send(self, message: str) -> None:
        if requests_module is None:  # pragma: no cover
            LOGGER.warning("%s 通知を送信できません（requests 未インポート）", self.name)
            return

        payload = {"text": message}

        if self.username:
            payload["username"] = self.username
        if self.icon_emoji:
            payload["icon_emoji"] = self.icon_emoji

        try:
            response = requests_module.post(self.webhook_url, json=payload, timeout=NOTIFICATION_TIMEOUT)
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - 通信環境依存
            LOGGER.error("%s 通知の送信に失敗しました: %s", self.name, exc)


class LineNotification(NotificationChannel):
    """LINE Messaging API を利用した通知チャネル。"""

    def __init__(self, channel_token: str, target_ids: Sequence[str]) -> None:
        super().__init__("LINE")
        self.channel_token = channel_token
        self.target_ids = list(target_ids)

    @classmethod
    def from_env(cls) -> Optional["LineNotification"]:
        channel_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        target_ids_raw = os.getenv("LINE_TARGET_IDS")

        if not channel_token or not target_ids_raw:
            return None

        if requests_module is None:
            LOGGER.warning("requests が利用できないため LINE 通知は無効化されます。")
            return None

        target_ids = [tid.strip() for tid in target_ids_raw.split(",") if tid.strip()]
        if not target_ids:
            return None

        return cls(channel_token=channel_token, target_ids=target_ids)

    def send(self, message: str) -> None:
        headers = {
            "Authorization": f"Bearer {self.channel_token}",
            "Content-Type": "application/json",
        }

        if requests_module is None:  # pragma: no cover
            LOGGER.warning("%s 通知を送信できません（requests 未インポート）", self.name)
            return

        for target_id in self.target_ids:
            payload = {
                "to": target_id,
                "messages": [
                    {
                        "type": "text",
                        "text": message,
                    }
                ],
            }

            try:
                response = requests_module.post(
                    "https://api.line.me/v2/bot/message/push",
                    json=payload,
                    headers=headers,
                    timeout=NOTIFICATION_TIMEOUT,
                )
                response.raise_for_status()
            except Exception as exc:  # pragma: no cover - 通信環境依存
                LOGGER.error("%s 通知の送信に失敗しました（target=%s）: %s", self.name, target_id, exc)


class NotificationManager:
    """複数の通知チャネルをまとめて管理する。"""

    def __init__(self, channels: Iterable[NotificationChannel]) -> None:
        self.channels = list(channels)

    def send(self, message: str) -> None:
        if not self.channels:
            return

        for channel in self.channels:
            try:
                channel.send(message)
            except Exception as exc:  # pragma: no cover - 念のための保護
                LOGGER.error("通知チャネル %s の送信中に予期せぬエラー: %s", channel.name, exc)


def build_notification_manager() -> NotificationManager:
    channels: List[NotificationChannel] = []

    slack_channel = SlackNotification.from_env()
    if slack_channel:
        channels.append(slack_channel)

    line_channel = LineNotification.from_env()
    if line_channel:
        channels.append(line_channel)

    if not channels:
        LOGGER.debug("通知チャネルが設定されていないため、通知送信は行われません。")

    return NotificationManager(channels)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    default_command = [sys.executable, "main.py", "--schedule"]
    command = _parse_command(default_command)

    restart_delay_env = os.getenv("NIKUNE_RESTART_DELAY", "5")
    try:
        restart_delay = int(restart_delay_env)
    except ValueError:
        LOGGER.warning(
            "Invalid NIKUNE_RESTART_DELAY value '%s'; falling back to default (5 seconds).",
            restart_delay_env,
        )
        restart_delay = 5

    restart_on_success = _env_flag("NIKUNE_RESTART_ON_SUCCESS", default=False)

    max_restarts = os.getenv("NIKUNE_MAX_RESTARTS")
    if max_restarts:
        try:
            max_restart_count = int(max_restarts)
        except ValueError:
            LOGGER.warning(
                "NIKUNE_MAX_RESTARTS is set to a non-integer value (%r); falling back to unlimited restarts.",
                max_restarts,
            )
            max_restart_count = None
    else:
        max_restart_count = None

    host = socket.gethostname()
    LOGGER.info("nikune service runner starting on host %s", host)
    LOGGER.info("service command: %s", command)

    should_stop = False
    restarts = 0

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal should_stop
        LOGGER.info("Signal %s received. Stopping after current process exits.", signum)
        should_stop = True

    # Windows では SIGTERM が存在しないため、プラットフォーム判定
    signals = [signal.SIGINT]
    if platform.system() != "Windows":
        signals.append(signal.SIGTERM)

    for sig in signals:
        signal.signal(sig, _handle_signal)

    notification_manager = build_notification_manager()

    while True:
        start_time = time.time()
        LOGGER.info("Launching nikune scheduler process...")
        process = subprocess.Popen(command)

        try:
            return_code = process.wait()
        except KeyboardInterrupt:
            LOGGER.info("KeyboardInterrupt received. Terminating child process...")
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                LOGGER.warning("Child process did not terminate gracefully. Forcing kill...")
                process.kill()
                process.wait()
            return_code = 0
            should_stop = True

        runtime = time.time() - start_time
        LOGGER.info("Process exited with code %s after %.1f seconds.", return_code, runtime)

        # 異常終了時は通知を送信
        if return_code != 0:
            notification_manager.send(
                f"[WARNING] nikune scheduler exited with code {return_code} "
                f"(runtime: {runtime:.1f}s) on host {host}. Restarting..."
            )

        if should_stop:
            LOGGER.info("Stop flag detected. Exiting service runner.")
            break

        if return_code == 0 and not restart_on_success:
            LOGGER.info("Process exited normally. Service runner will stop.")
            break

        # 再起動する場合はカウントを増やす（正常終了・異常終了問わず）
        restarts += 1

        if max_restart_count is not None and restarts > max_restart_count:
            LOGGER.error("Max restart count (%s) exceeded. Stopping service runner.", max_restart_count)
            notification_manager.send(
                f"[CRITICAL] nikune service exceeded max restart count ({max_restart_count}) "
                f"on host {host}. Manual intervention required."
            )
            break

        LOGGER.info("Restarting in %s seconds...", restart_delay)
        time.sleep(restart_delay)

    LOGGER.info("Service runner stopped.")


if __name__ == "__main__":
    main()
