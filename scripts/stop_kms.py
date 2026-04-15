from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def _default_pid_file() -> Path:
    return ROOT / ".run-logs" / "kms-api.pid.json"


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop kms-api using the recorded pid.")
    parser.add_argument("--pid-file", type=str, default=str(_default_pid_file()), help="Path to pid metadata json.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Graceful shutdown timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pid_file = Path(args.pid_file).resolve()
    if not pid_file.exists():
        print(json.dumps({"status": "not_running", "reason": "pid_file_missing", "pid_file": str(pid_file)}, ensure_ascii=False))
        return 0

    payload = json.loads(pid_file.read_text(encoding="utf-8"))
    pid = int(payload.get("pid") or 0)
    if pid <= 0 or not _pid_exists(pid):
        pid_file.unlink(missing_ok=True)
        print(json.dumps({"status": "not_running", "reason": "stale_pid_file", "pid_file": str(pid_file)}, ensure_ascii=False))
        return 0

    try:
        if os.name == "nt":
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pid_file.unlink(missing_ok=True)
        print(json.dumps({"status": "stopped", "pid": pid, "mode": "already_gone", "pid_file": str(pid_file)}, ensure_ascii=False))
        return 0

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if not _pid_exists(pid):
            pid_file.unlink(missing_ok=True)
            print(json.dumps({"status": "stopped", "pid": pid, "mode": "graceful", "pid_file": str(pid_file)}, ensure_ascii=False))
            return 0
        time.sleep(0.5)

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not _pid_exists(pid):
            pid_file.unlink(missing_ok=True)
            print(json.dumps({"status": "stopped", "pid": pid, "mode": "forced", "pid_file": str(pid_file)}, ensure_ascii=False))
            return 0
        time.sleep(0.5)

    print(json.dumps({"status": "failed", "pid": pid, "reason": "still_running", "pid_file": str(pid_file)}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
