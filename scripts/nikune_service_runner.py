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
import platform
import shlex
import signal
import socket
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
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


# 子プロセスの生存確認ポーリング間隔（秒）
CHILD_WAIT_POLL_INTERVAL = 0.5

# シャットダウン要求後、terminate()からkill()に切り替えるまでの猶予秒数
SHUTDOWN_GRACE_PERIOD = 10.0


class _RunnerState:
    """シグナルハンドラとメインループの間で共有するシャットダウン状態。"""

    def __init__(self) -> None:
        self.should_stop = False

    def request_stop(self, signum: int) -> None:
        LOGGER.info("Signal %s received. Stopping after current process exits.", signum)
        self.should_stop = True


def _wait_for_child_process(
    process: subprocess.Popen[bytes],
    state: _RunnerState,
    poll_interval: float = CHILD_WAIT_POLL_INTERVAL,
    grace_period: float = SHUTDOWN_GRACE_PERIOD,
) -> int:
    """
    子プロセスの終了を待つ。

    以前の実装は `process.wait()` を無条件・無期限にブロックしており、
    SIGTERM/SIGINTのハンドラが `should_stop` フラグを立てるだけだったため、
    シグナル受信後もこの呼び出しが子プロセスの自然な終了を待ち続けてしまい、
    運用者がタイムアウトしてSIGKILLするとこの中断で子プロセス（スケジューラー）
    が孤児化する問題があった。

    ここではタイムアウト付きの `wait()` をポーリングし、`state.should_stop` を
    毎回確認することで、シグナル受信後は能動的に `terminate()` を呼び出し、
    猶予期間内に終了しなければ `kill()` で確実にクリーンアップする。
    """
    terminate_requested_at: Optional[float] = None

    while True:
        try:
            return process.wait(timeout=poll_interval)
        except subprocess.TimeoutExpired:
            pass
        except KeyboardInterrupt:
            # signalモジュール経由のハンドリングをすり抜けた場合の保険
            state.should_stop = True

        if not state.should_stop:
            continue

        if terminate_requested_at is None:
            LOGGER.info("Shutdown requested. Terminating child process (pid=%s)...", process.pid)
            try:
                process.terminate()
            except ProcessLookupError:
                # 既に終了している場合は次のwait()で回収される
                pass
            terminate_requested_at = time.time()
        elif time.time() - terminate_requested_at > grace_period:
            LOGGER.warning("Child process did not terminate gracefully. Forcing kill...")
            try:
                process.kill()
            except ProcessLookupError:
                pass
            return process.wait()


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

    state = _RunnerState()
    restarts = 0

    def _handle_signal(signum: int, _frame: object) -> None:
        state.request_stop(signum)

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

        return_code = _wait_for_child_process(process, state)

        runtime = time.time() - start_time
        LOGGER.info("Process exited with code %s after %.1f seconds.", return_code, runtime)

        # シャットダウン要求による意図的な終了の場合は異常終了通知を送らない
        # （terminate()/kill()によりreturn_codeが非0になり得るため）
        if return_code != 0 and not state.should_stop:
            notification_manager.send(
                f"[WARNING] nikune scheduler exited with code {return_code} "
                f"(runtime: {runtime:.1f}s) on host {host}. Restarting..."
            )

        if state.should_stop:
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
