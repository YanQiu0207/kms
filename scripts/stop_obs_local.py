from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
OBS_LOCAL_ROOT = ROOT / "obs-local"
DEFAULT_CONFIG_PATH = OBS_LOCAL_ROOT / "config.yaml"
DEFAULT_PID_FILE = OBS_LOCAL_ROOT / "data" / "logs" / "obs-local.pid.json"
_DEFAULT_TASK_NAME = "mykms-start-obs-local"

from process_utils import find_listening_pid, pid_exists, request_stop


def _load_obs_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"obs-local config must be a mapping: {path}")
    return payload


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _schtask_end(task_name: str) -> tuple[bool, str]:
    """Send End signal to a Windows scheduled task via schtasks /End.

    Returns (success, detail) where success=True means the command was accepted
    by Task Scheduler (does not guarantee processes have exited yet).
    """
    result = subprocess.run(
        ["schtasks", "/End", "/TN", task_name],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        return True, result.stdout.strip() or "ok"
    return False, (result.stderr.strip() or result.stdout.strip() or f"rc={result.returncode}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop obs-local backend and frontend.")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH), help="Path to obs-local config.yaml.")
    parser.add_argument("--backend-port", type=int, default=None, help="Override backend port.")
    parser.add_argument("--frontend-port", type=int, default=4174, help="Frontend dev server port.")
    parser.add_argument("--pid-file", type=str, default=str(DEFAULT_PID_FILE), help="Path to pid metadata json.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Graceful shutdown timeout in seconds.")
    parser.add_argument(
        "--task-name",
        type=str,
        default=_DEFAULT_TASK_NAME if os.name == "nt" else "",
        help="Windows scheduled task name to stop via schtasks /End (Windows only; set to empty to skip).",
    )
    return parser.parse_args()


def _stop_one(pid: int, label: str, timeout: float) -> dict:
    if not pid_exists(pid):
        return {"label": label, "status": "not_running", "pid": pid}

    try:
        stop_mode = request_stop(pid)
    except OSError as exc:
        # PermissionError (e.g. SYSTEM process) also lands here.
        # Return a placeholder; caller must verify port is actually closed.
        return {"label": label, "status": "_signal_failed", "pid": pid, "stop_error": str(exc)}

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_exists(pid):
            return {"label": label, "status": "stopped", "pid": pid, "mode": stop_mode}
        time.sleep(0.5)

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not pid_exists(pid):
            return {"label": label, "status": "stopped", "pid": pid, "mode": "forced"}
        time.sleep(0.5)

    return {"label": label, "status": "failed", "pid": pid, "reason": "still_running"}


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = _load_obs_config(config_path)

    server = config.get("server") if isinstance(config.get("server"), dict) else {}
    backend_host = str(server.get("host") or "127.0.0.1")
    backend_port = args.backend_port or int(server.get("port") or 49154)
    frontend_port = args.frontend_port
    pid_file = Path(args.pid_file).resolve()

    # --- Windows scheduled-task fast path ---
    # When obs-local runs as a SYSTEM-level scheduled task, TerminateProcess is
    # denied even from an admin shell. schtasks /End terminates the entire Job
    # Object (including uvicorn and npm children) through the Task Scheduler
    # service, which has the necessary privileges.
    task_name = args.task_name.strip() if os.name == "nt" else ""
    if task_name:
        schtask_ok, schtask_detail = _schtask_end(task_name)
        # Always wait: schtasks /End terminates the Job Object asynchronously.
        # Even when it returns a non-zero exit code (e.g., "no running instance"),
        # the underlying job termination may still be in progress, so wait briefly.
        wait_seconds = args.timeout if schtask_ok else 5.0
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            backend_up = _port_open(backend_host, backend_port)
            frontend_up = _port_open("127.0.0.1", frontend_port)
            if not backend_up and not frontend_up:
                pid_file.unlink(missing_ok=True)
                results = [
                    {"label": "backend", "status": "stopped", "mode": "schtask", "task": task_name},
                    {"label": "frontend", "status": "stopped", "mode": "schtask", "task": task_name},
                ]
                print(json.dumps({"status": "stopped", "processes": results, "pid_file": str(pid_file)}, ensure_ascii=False))
                return 0
        # Ports still open after wait — fall through to per-process kill

    stored: dict = {}
    if pid_file.exists():
        try:
            stored = json.loads(pid_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = {}

    def _resolve_pid(port: int, key: str) -> tuple[int | None, str]:
        live_pid = find_listening_pid(port)
        if live_pid:
            return live_pid, "netstat"
        entry = stored.get(key) or {}
        raw = entry.get("pid")
        return (int(raw) if raw else None), "pid_file"

    backend_pid, backend_pid_src = _resolve_pid(backend_port, "backend")
    frontend_pid, frontend_pid_src = _resolve_pid(frontend_port, "frontend")

    results: list[dict] = []

    if backend_pid and pid_exists(backend_pid):
        r = _stop_one(backend_pid, "backend", args.timeout)
        r["pid_src"] = backend_pid_src
        if r["status"] == "_signal_failed":
            r = {"label": "backend", "pid": backend_pid, "pid_src": backend_pid_src,
                 "status": "failed" if _port_open(backend_host, backend_port) else "stopped",
                 "mode": "already_gone", "stop_error": r.get("stop_error")}
        results.append(r)
    else:
        results.append({"label": "backend", "status": "not_running", "host": backend_host, "port": backend_port,
                        "pid": backend_pid, "pid_src": backend_pid_src})

    if frontend_pid and pid_exists(frontend_pid):
        r = _stop_one(frontend_pid, "frontend", args.timeout)
        r["pid_src"] = frontend_pid_src
        if r["status"] == "_signal_failed":
            r = {"label": "frontend", "pid": frontend_pid, "pid_src": frontend_pid_src,
                 "status": "failed" if _port_open("127.0.0.1", frontend_port) else "stopped",
                 "mode": "already_gone", "stop_error": r.get("stop_error")}
        results.append(r)
    else:
        results.append({"label": "frontend", "status": "not_running", "port": frontend_port,
                        "pid": frontend_pid, "pid_src": frontend_pid_src})

    all_done = all(r["status"] in {"stopped", "not_running"} for r in results)
    any_failed = any(r["status"] == "failed" for r in results)

    if all_done:
        pid_file.unlink(missing_ok=True)

    overall = "failed" if any_failed else ("stopped" if all_done else "partial")
    print(json.dumps({"status": overall, "processes": results, "pid_file": str(pid_file)}, ensure_ascii=False))
    return 0 if not any_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
