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

    通知（Slack / LINE）の設定は nikune/notifications.py を参照。
"""

from __future__ import annotations

import logging
import os
import platform
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

# `python scripts/nikune_service_runner.py` と直接起動された場合でも nikune パッケージを import できるようにする
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nikune.notifications import _env_flag, build_notification_manager  # noqa: E402  # isort: skip

LOGGER = logging.getLogger("nikune.service_runner")


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
