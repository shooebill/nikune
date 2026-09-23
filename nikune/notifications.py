"""
nikune の障害通知（Slack / LINE）
=================================

見張り役（scripts/nikune_service_runner.py）とログ確認スクリプト（scripts/check_logs.py）の
両方から使う通知の部品。送信先は環境変数で決まる。

主な環境変数:
    - NIKUNE_NOTIFICATION_TIMEOUT:
        通知送信時のタイムアウト秒数（既定: 5）
    - SLACK_WEBHOOK_URL:
        Slack 通知用 Incoming Webhook URL（任意）
    - SLACK_WEBHOOK_USERNAME / SLACK_WEBHOOK_ICON_EMOJI:
        Slack 通知のユーザー名・アイコン（任意）
    - LINE_CHANNEL_ACCESS_TOKEN:
        LINE Messaging API のチャネルアクセストークン（任意）
    - LINE_NOTIFY_ENABLED:
        LINE通知（broadcast）を有効にするか（true/false, 既定: false）。
        運用開始直後はSlackのみ通知し、監視頻度が下がった段階で有効化する想定。
    - NIKUNE_NOTIFICATION_FAILURE_MARKER:
        Slack/LINEとも通知送信に失敗した場合に追記するマーカーファイルのパス
        （既定: "logs/notification_failure.marker"）。Webhook失効等で通知経路が
        死んでいても、このファイルの更新日時を監視すれば異常に気づける。
"""

from __future__ import annotations

import importlib
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Iterable, List, Optional

requests_module: Optional[ModuleType]
try:
    requests_module = importlib.import_module("requests")
except ImportError:
    requests_module = None

LOGGER = logging.getLogger("nikune.notifications")

# 通知送信時のタイムアウト秒数（環境変数で上書き可能）
try:
    NOTIFICATION_TIMEOUT = int(os.getenv("NIKUNE_NOTIFICATION_TIMEOUT", "5"))
except (TypeError, ValueError):
    NOTIFICATION_TIMEOUT = 5


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
    def send(self, message: str) -> bool:
        """
        通知を送信する。

        Returns:
            送信に成功したかどうか。NotificationManagerが「全チャネル送信失敗」を
            検知するために使用するため、実装側は例外を握りつぶさずFalseを返すこと。
        """


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

    def send(self, message: str) -> bool:
        if requests_module is None:  # pragma: no cover
            LOGGER.warning("%s 通知を送信できません（requests 未インポート）", self.name)
            return False

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
            return False

        return True


class LineNotification(NotificationChannel):
    """LINE Messaging API の broadcast を利用した通知チャネル（友だち全員に配信、userId管理不要）。"""

    def __init__(self, channel_token: str) -> None:
        super().__init__("LINE")
        self.channel_token = channel_token

    @classmethod
    def from_env(cls) -> Optional["LineNotification"]:
        # 運用開始直後はSlackのみ通知する方針のため、既定では無効（LINE_NOTIFY_ENABLED=true で有効化）
        if not _env_flag("LINE_NOTIFY_ENABLED", default=False):
            return None

        channel_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        if not channel_token:
            return None

        if requests_module is None:
            LOGGER.warning("requests が利用できないため LINE 通知は無効化されます。")
            return None

        return cls(channel_token=channel_token)

    def send(self, message: str) -> bool:
        if requests_module is None:  # pragma: no cover
            LOGGER.warning("%s 通知を送信できません（requests 未インポート）", self.name)
            return False

        headers = {
            "Authorization": f"Bearer {self.channel_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messages": [
                {
                    "type": "text",
                    "text": message,
                }
            ],
        }

        try:
            response = requests_module.post(
                "https://api.line.me/v2/bot/message/broadcast",
                json=payload,
                headers=headers,
                timeout=NOTIFICATION_TIMEOUT,
            )
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - 通信環境依存
            LOGGER.error("%s 通知の送信に失敗しました: %s", self.name, exc)
            return False

        return True


def _notification_failure_marker_path() -> Path:
    """
    通知が全チャネルで失敗した際に書き出すマーカーファイルのパス。

    NIKUNE_NOTIFICATION_FAILURE_MARKER 環境変数で上書きできる
    （既定はプロジェクトルート直下の logs/notification_failure.marker）。
    """
    override = os.getenv("NIKUNE_NOTIFICATION_FAILURE_MARKER")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "logs" / "notification_failure.marker"


def _write_notification_failure_marker(message: str) -> None:
    """
    通知の全チャネル送信失敗時の最後の砦。

    Slack Webhookの失効やLINEトークンの期限切れなどで通知経路そのものが
    死んでいる場合、ログにERRORを出すだけでは誰も気づけない可能性がある。
    運用者がファイルの存在・更新日時を監視できるよう、ローカルの既知の場所に
    検知しやすい形でマーカーを残す（過剰な仕組みは避け、追記のみの最小実装）。
    """
    marker_path = _notification_failure_marker_path()
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with marker_path.open("a", encoding="utf-8") as marker_file:
            marker_file.write(f"{timestamp} | {message}\n")
    except OSError as exc:  # pragma: no cover - ファイルシステム依存
        LOGGER.error("通知失敗マーカーファイルの書き込みにも失敗しました（%s）: %s", marker_path, exc)


class NotificationManager:
    """複数の通知チャネルをまとめて管理する。"""

    def __init__(self, channels: Iterable[NotificationChannel]) -> None:
        self.channels = list(channels)

    def send(self, message: str) -> bool:
        """
        全チャネルへ通知を送信する。

        Returns:
            いずれか1チャネルでも送信に成功したかどうか。チャネルが1つも
            設定されていない場合はFalseを返す（この場合はマーカーは書かない。
            未設定は意図した状態であり得るため、設定済みチャネルが実際に
            失敗したケースと区別する）。
        """
        if not self.channels:
            LOGGER.debug("通知チャネルが設定されていないため、通知は送信されません: %s", message)
            return False

        any_success = False
        for channel in self.channels:
            try:
                if channel.send(message):
                    any_success = True
            except Exception as exc:  # pragma: no cover - 念のための保護
                LOGGER.error("通知チャネル %s の送信中に予期せぬエラー: %s", channel.name, exc)

        if not any_success:
            channel_names = ", ".join(channel.name for channel in self.channels)
            LOGGER.error(
                "全ての通知チャネル（%s）への送信に失敗しました。"
                "このアラートは運用者に届いていない可能性があります: %s",
                channel_names,
                message,
            )
            _write_notification_failure_marker(message)

        return any_success


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
