from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_config, resolve_config_path
from process_utils import find_listening_pid, pid_exists, request_stop


def _default_pid_file() -> Path:
    return ROOT / ".run-logs" / "kms-api.pid.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop kms-api using the recorded pid.")
    parser.add_argument("--config", type=str, default=None, help="Optional config file path.")
    parser.add_argument("--host", type=str, default=None, help="Override host.")
    parser.add_argument("--port", type=int, default=None, help="Override port.")
    parser.add_argument("--pid-file", type=str, default=str(_default_pid_file()), help="Path to pid metadata json.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Graceful shutdown timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_config_path(args.config)
    config = load_config(config_path)
    host = args.host or config.server.host
    port = args.port or config.server.port
    pid_file = Path(args.pid_file).resolve()
    listening_pid = find_listening_pid(port)
    if not pid_file.exists():
        if not listening_pid or not pid_exists(listening_pid):
            print(
                json.dumps(
                    {"status": "not_running", "reason": "pid_file_missing", "pid_file": str(pid_file), "host": host, "port": port},
                    ensure_ascii=False,
                )
            )
            return 0
        payload = {"pid": listening_pid}
    else:
        payload = json.loads(pid_file.read_text(encoding="utf-8"))

    pid = int(payload.get("pid") or 0)
    if listening_pid and pid_exists(listening_pid):
        pid = listening_pid
    elif pid <= 0 or not pid_exists(pid):
        pid_file.unlink(missing_ok=True)
        print(
            json.dumps(
                {"status": "not_running", "reason": "stale_pid_file", "pid_file": str(pid_file), "host": host, "port": port},
                ensure_ascii=False,
            )
        )
        return 0

    try:
        stop_mode = request_stop(pid)
    except OSError:
        pid_file.unlink(missing_ok=True)
        print(json.dumps({"status": "stopped", "pid": pid, "mode": "already_gone", "pid_file": str(pid_file)}, ensure_ascii=False))
        return 0

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if not pid_exists(pid):
            pid_file.unlink(missing_ok=True)
            print(json.dumps({"status": "stopped", "pid": pid, "mode": stop_mode, "pid_file": str(pid_file)}, ensure_ascii=False))
            return 0
        time.sleep(0.5)

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not pid_exists(pid):
            pid_file.unlink(missing_ok=True)
            print(json.dumps({"status": "stopped", "pid": pid, "mode": "forced", "pid_file": str(pid_file)}, ensure_ascii=False))
            return 0
        time.sleep(0.5)

    print(json.dumps({"status": "failed", "pid": pid, "reason": "still_running", "pid_file": str(pid_file)}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
