#!/usr/bin/env python3
"""
nikune log checker
==================

本番（wren）は cron が `main.py --post-now` / `--quote-check` を1回ずつ起動する方式のため、
見張り役（nikune_service_runner.py）の通知は使われない。代わりにこのスクリプトを各回の数分後に
cron から起動し、その回のログを読んで異常があるときだけ Slack（/LINE）に通知する。

基本的な使い方:

    $ python scripts/check_logs.py post 09:00
    $ python scripts/check_logs.py quote 12:30
    $ python scripts/check_logs.py post 09:00 --log-file /tmp/test.log --dry-run   # 送信せずに通知文を表示

通知する条件（どれか1つでも該当したら通知。レベルが WARNING の行を一律に通知することはしない）:
    - その回に成功の記録がない（cron が動かなかった・起動時に落ちた・固まった場合もここで拾う）
    - 失敗の記録がある（❌ の失敗メッセージ、レベル ERROR の行、Traceback）
    - TypeSafe でチェックできなかった（投稿: decision=UNCHECKED、引用RT: decision=UNAVAILABLE）
    - TypeSafe のキーが設定されていない（投稿: decision=DISABLED。本番にはキーがあるので設定漏れ）
    - Jev の警告（投稿: decision=WARN）

主な環境変数:
    - NIKUNE_LOG_DIR:
        post.log / quote.log の置き場所（既定: /mnt/data/nikune/logs）。--log-file で個別に上書きできる
    - 通知（Slack / LINE）の設定は nikune/notifications.py を参照
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Protocol, Sequence, Set

# `python scripts/check_logs.py` と直接起動された場合でも nikune パッケージを import できるようにする
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402  # isort: skip

from nikune.notifications import build_notification_manager  # noqa: E402  # isort: skip

DEFAULT_LOG_DIR = "/mnt/data/nikune/logs"

# その回のログとみなす範囲（予定時刻からの分数）。次の回（最短でも数時間後）を誤って拾わないための上限
DEFAULT_WINDOW_MINUTES = 30

# 通知に添えるログ行の上限（行数・1行あたりの文字数）
MAX_LINES_IN_MESSAGE = 8
MAX_LINE_LENGTH = 300

# main.py の LOG_FORMAT（"%(asctime)s - %(name)s - %(levelname)s - %(message)s"）に対応する
LOG_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} - (\S+) - ([A-Z]+) - (.*)$")

# 失敗の記録（ERROR レベルの行・Traceback はこれとは別に判定する）
FAILURE_MARKERS = (
    "❌ Operation failed",
    "❌ Unexpected error:",
    "❌ Failed to post tweet",
    "❌ Quote retweet check failed:",
)

# 通知文に載せる前に伏せ字にする秘密情報のパターン
_SECRET_PATTERNS = (
    (re.compile(r"https://hooks\.slack\.com/\S+"), "https://hooks.slack.com/***"),
    (re.compile(r"(?i)\bBearer\s+\S+"), "Bearer ***"),
    (re.compile(r"\bxox[a-z]-[\w-]+"), "xox*-***"),
    (
        re.compile(
            r"(?i)\b([\w-]*(?:api[_-]?key|token|secret|password|authorization)[\w-]*)([\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"
        ),
        r"\1\2***",
    ),
)

# 値そのものが載っていたら伏せ字にする環境変数（.env に置いている秘密の値）
_SECRET_ENV_KEYS = (
    "SLACK_WEBHOOK_URL",
    "LINE_CHANNEL_ACCESS_TOKEN",
    "TYPESAFE_API_KEY",
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_TOKEN_SECRET",
    "TWITTER_BEARER_TOKEN",
)


@dataclass(frozen=True)
class Target:
    """確認対象（投稿 / 引用RT）ごとの設定"""

    label: str
    log_name: str
    success_markers: Sequence[str]
    jev_marker: str
    jev_alert_decisions: Sequence[str]


TARGETS = {
    "post": Target(
        label="投稿",
        log_name="post.log",
        success_markers=("Tweet posted successfully! ID:",),
        jev_marker="🧭 Jev pre-post check:",
        jev_alert_decisions=("UNCHECKED", "DISABLED", "WARN"),
    ),
    "quote": Target(
        label="引用RT",
        log_name="quote.log",
        # レート制限で引用しなかった回は「Quote retweet check completed」が出ないが、正常終了の記録は出る
        success_markers=("✅ Quote retweet check completed:", "✅ Operation completed successfully"),
        jev_marker="🧭 Jev quote check:",
        jev_alert_decisions=("UNAVAILABLE",),
    ),
}

_JEV_REASONS = {
    "UNCHECKED": "TypeSafe でチェックできませんでした",
    "UNAVAILABLE": "TypeSafe でチェックできませんでした",
    "DISABLED": "TypeSafe のキーが設定されていません（チェックなしで投稿）",
    "WARN": "Jev の警告があります",
}


@dataclass
class CheckResult:
    """1回分の確認結果。reasons が空なら正常"""

    reasons: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    evidence_note: str = ""

    @property
    def ok(self) -> bool:
        return not self.reasons

    def add(self, reason: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)


class Notifier(Protocol):
    def send(self, message: str) -> bool: ...


def mask_secrets(text: str) -> str:
    """ログ行を通知に貼る前に、Webhook URL・トークン・API キーらしきものを伏せ字にする"""
    for key in _SECRET_ENV_KEYS:
        value = os.getenv(key)
        if value and len(value) >= 8:
            text = text.replace(value, "***")
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _lines_in_window(lines: Sequence[str], start: datetime, end: datetime) -> List[str]:
    """
    [start, end) のタイムスタンプを持つ行を返す。

    タイムスタンプのない行（Traceback や print の出力）は直前のタイムスタンプ付きの行と同じ回のものとみなす。
    起動直後（ログ設定より前）に落ちた場合の Traceback は前の回の続きに見えて範囲外になるが、
    その場合は「成功の記録がない」で拾い、通知にはファイル末尾の行を添える。
    """
    selected: List[str] = []
    current: Optional[datetime] = None
    for line in lines:
        match = LOG_LINE_RE.match(line)
        if match:
            current = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
        if current is not None and start <= current < end:
            selected.append(line)
    return selected


def _decision(line: str) -> Optional[str]:
    match = re.search(r"\bdecision=([A-Z]+)", line)
    return match.group(1) if match else None


def check_log(target: Target, log_path: Path, start: datetime, end: datetime) -> CheckResult:
    """指定した回（start〜end）のログを読み、通知すべき異常を集める"""
    result = CheckResult()
    if not log_path.exists():
        result.add(f"ログファイルがありません（{log_path}）")
        return result

    all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    lines = _lines_in_window(all_lines, start, end)

    # 通知に添える行（ウィンドウ内の位置）。最後にファイル順に並べ直す
    evidence_index: Set[int] = set()

    if not any(marker in line for line in lines for marker in target.success_markers):
        result.add("成功の記録がありません")
        if lines:
            evidence_index.update(range(max(0, len(lines) - 5), len(lines)))
        else:
            # その回の行が1行もない（cron が動かなかった、または起動時に落ちた）。原因の手がかりに末尾を添える
            result.evidence_note = "この回のログがないため、ファイル末尾を添付"
            result.evidence.extend(all_lines[-5:])

    for index, line in enumerate(lines):
        match = LOG_LINE_RE.match(line)
        level = match.group(3) if match else None
        if level == "ERROR" or line.startswith("Traceback") or any(marker in line for marker in FAILURE_MARKERS):
            result.add("失敗の記録があります")
            evidence_index.add(index)
        if target.jev_marker in line:
            decision = _decision(line)
            if decision is not None and decision in target.jev_alert_decisions:
                result.add(_JEV_REASONS[decision])
                evidence_index.add(index)

    result.evidence.extend(lines[index] for index in sorted(evidence_index))
    return result


def build_message(target: Target, scheduled: str, result: CheckResult, host: str) -> str:
    """通知文（秘密情報は伏せ字にし、ログ行は数行・1行あたりの文字数を制限する）"""
    header = f"[nikune] {scheduled} の{target.label}: {'／'.join(result.reasons)}"
    body = [header, f"host: {host}"]
    evidence = [line[:MAX_LINE_LENGTH] for line in result.evidence[-MAX_LINES_IN_MESSAGE:]]
    if evidence:
        body.append(f"ログ（{result.evidence_note}）:" if result.evidence_note else "ログ:")
        body.append("```\n" + "\n".join(evidence) + "\n```")
    return mask_secrets("\n".join(body))


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="nikune のログを確認し、異常があれば通知する")
    parser.add_argument("target", choices=sorted(TARGETS), help="確認対象（post=独り言投稿 / quote=引用RT）")
    parser.add_argument("scheduled", help="その回の予定時刻（HH:MM）")
    parser.add_argument("--date", help="その回の日付（YYYY-MM-DD、既定: 今日）")
    parser.add_argument("--log-file", help="読むログファイル（既定: $NIKUNE_LOG_DIR/<post|quote>.log）")
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=DEFAULT_WINDOW_MINUTES,
        help=f"予定時刻から何分までをその回のログとみなすか（既定: {DEFAULT_WINDOW_MINUTES}）",
    )
    parser.add_argument("--dry-run", action="store_true", help="通知を送らず、通知文を表示するだけにする")
    return parser.parse_args(argv)


def run(args: argparse.Namespace, notifier_factory: Callable[[], Notifier]) -> int:
    """確認して、異常があれば通知する。戻り値は終了コード（0: 正常、1: 異常あり）"""
    target = TARGETS[args.target]
    scheduled_time = time.fromisoformat(args.scheduled)
    run_date = date.fromisoformat(args.date) if args.date else date.today()
    start = datetime.combine(run_date, scheduled_time)
    end = start + timedelta(minutes=args.window_minutes)
    log_path = (
        Path(args.log_file) if args.log_file else Path(os.getenv("NIKUNE_LOG_DIR", DEFAULT_LOG_DIR)) / target.log_name
    )

    result = check_log(target, log_path, start, end)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = f"{stamp} check_logs {args.target} {run_date} {args.scheduled}"

    if result.ok:
        print(f"{summary}: OK")
        return 0

    message = build_message(target, args.scheduled, result, socket.gethostname())
    if args.dry_run:
        print(f"{summary}: ANOMALY (dry-run, not sent)\n{message}")
        return 1

    sent = notifier_factory().send(message)
    print(f"{summary}: ANOMALY ({'notified' if sent else 'NOT notified'}) - {' / '.join(result.reasons)}")
    return 1


def main(
    argv: Optional[Sequence[str]] = None,
    notifier_factory: Callable[[], Notifier] = build_notification_manager,
) -> int:
    args = _parse_args(argv)
    load_dotenv(PROJECT_ROOT / ".env")
    try:
        return run(args, notifier_factory)
    except Exception as exc:  # noqa: BLE001 - 見張りが黙って止まらないよう、自分自身の失敗も通知する
        message = mask_secrets(
            f"[nikune] ログ確認スクリプト自体が失敗しました（{args.target} {args.scheduled}）: "
            f"{type(exc).__name__}: {exc}\nhost: {socket.gethostname()}"
        )
        print(message, file=sys.stderr)
        if not args.dry_run:
            try:
                notifier_factory().send(message)
            except Exception as send_exc:  # noqa: BLE001
                print(f"通知の送信にも失敗しました: {type(send_exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
