from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from process_utils import find_listening_pid, pid_exists

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import CONFIG_ENV_VAR, SERVER_HOST_ENV_VAR, SERVER_PORT_ENV_VAR, load_config, resolve_config_path
from app.timefmt import format_local_datetime


def _default_log_dir() -> Path:
    return ROOT / ".run-logs"


def _resolve_runtime_python() -> str:
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt" and venv_python.exists():
        return str(venv_python)

    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)

    return sys.executable


def _wait_for_health(host: str, port: int, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    url = f"http://{host}:{port}/health"
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except URLError:
            time.sleep(1)
            continue
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start kms-api in the background.")
    parser.add_argument("--config", type=str, default=None, help="Optional config file path.")
    parser.add_argument("--host", type=str, default=None, help="Override host.")
    parser.add_argument("--port", type=int, default=None, help="Override port.")
    parser.add_argument("--log-dir", type=str, default=str(_default_log_dir()), help="Directory for log files.")
    parser.add_argument("--pid-file", type=str, default=None, help="Path to pid metadata json.")
    parser.add_argument("--timeout", type=float, default=60.0, help="Health check timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = resolve_config_path(args.config)
    config = load_config(config_path)
    host = args.host or config.server.host
    port = args.port or config.server.port

    log_dir = Path(args.log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    pid_file = Path(args.pid_file).resolve() if args.pid_file else log_dir / "kms-api.pid.json"
    stdout_path = log_dir / "kms-api.stdout.log"
    stderr_path = log_dir / "kms-api.stderr.log"

    listening_pid = find_listening_pid(port)
    if listening_pid and pid_exists(listening_pid):
        payload = {
            "pid": listening_pid,
            "host": host,
            "port": port,
            "config_path": str(config_path.resolve()),
            "python": "unknown",
            "log_dir": str(log_dir),
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "started_at": format_local_datetime(),
        }
        pid_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "already_running", **payload, "pid_file": str(pid_file)}, ensure_ascii=False))
        return 0

    if pid_file.exists():
        try:
            existing = json.loads(pid_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        existing_pid = int(existing.get("pid") or 0)
        if existing_pid and pid_exists(existing_pid):
            print(json.dumps({"status": "already_running", "pid": existing_pid, "pid_file": str(pid_file)}, ensure_ascii=False))
            return 0
        pid_file.unlink(missing_ok=True)

    env = os.environ.copy()
    env[CONFIG_ENV_VAR] = str(config_path.resolve())
    env[SERVER_HOST_ENV_VAR] = host
    env[SERVER_PORT_ENV_VAR] = str(port)
    env["KMS_LOG_DIR"] = str(log_dir)
    runtime_python = _resolve_runtime_python()

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    with stdout_path.open("ab") as stdout_handle, stderr_path.open("ab") as stderr_handle:
        process = subprocess.Popen(
            [runtime_python, "-m", "app.main"],
            cwd=str(ROOT),
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
        )

    deadline = time.time() + args.timeout
    ready = False
    listening_pid = None
    while time.time() < deadline:
        if process.poll() is not None:
            break
        listening_pid = find_listening_pid(port)
        if listening_pid and _wait_for_health(host, port, 2):
            ready = True
            break
        time.sleep(1)
    if not ready:
        if os.name == "nt":
            if process.poll() is None:
                process.terminate()
        else:
            if process.poll() is None:
                os.kill(process.pid, signal.SIGTERM)
        print(
            json.dumps(
                {
                    "status": "startup_failed" if process.poll() is not None else "startup_timeout",
                    "pid": process.pid,
                    "exit_code": process.poll(),
                    "host": host,
                    "port": port,
                    "stdout_log": str(stdout_path),
                    "stderr_log": str(stderr_path),
                },
                ensure_ascii=False,
            )
        )
        return 1

    payload = {
        "pid": listening_pid or process.pid,
        "host": host,
        "port": port,
        "config_path": str(config_path.resolve()),
        "python": runtime_python,
        "log_dir": str(log_dir),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "started_at": format_local_datetime(),
    }
    pid_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "started", **payload, "pid_file": str(pid_file)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
