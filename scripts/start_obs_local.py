from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import yaml


ROOT = Path(__file__).resolve().parents[1]
OBS_LOCAL_ROOT = ROOT / "obs-local"
OBS_FRONTEND_ROOT = OBS_LOCAL_ROOT / "frontend"
DEFAULT_CONFIG_PATH = OBS_LOCAL_ROOT / "config.yaml"


def _resolve_runtime_python() -> str:
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt" and venv_python.exists():
        return str(venv_python)

    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)

    return sys.executable


def _load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"obs-local config must be a mapping: {path}")
    return payload


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _wait_for_http(url: str, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return True
        except URLError:
            time.sleep(0.5)
            continue
    return False


def _npm_command() -> str:
    candidate = shutil.which("npm.cmd") or shutil.which("npm")
    if candidate:
        return candidate
    raise RuntimeError("npm was not found in PATH")


def _start_process(
    *,
    command: list[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    stdout_handle = stdout_path.open("ab")
    stderr_handle = stderr_path.open("ab")
    try:
        return subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start obs-local backend and frontend.")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH), help="Path to obs-local config.yaml")
    parser.add_argument("--backend-timeout", type=float, default=30.0, help="Backend health wait timeout in seconds")
    parser.add_argument("--frontend-timeout", type=float, default=30.0, help="Frontend health wait timeout in seconds")
    parser.add_argument("--frontend-port", type=int, default=4174, help="Frontend dev server port")
    parser.add_argument("--frontend-host", type=str, default="127.0.0.1", help="Frontend dev server host")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = _load_config(config_path)

    server = config.get("server") if isinstance(config.get("server"), dict) else {}
    backend_host = str(server.get("host") or "127.0.0.1")
    backend_port = int(server.get("port") or 49154)
    backend_url = f"http://{backend_host}:{backend_port}"
    backend_health_url = f"{backend_url}/api/health"

    frontend_host = str(args.frontend_host)
    frontend_port = int(args.frontend_port)
    frontend_url = f"http://{frontend_host}:{frontend_port}"

    runtime_python = _resolve_runtime_python()
    npm = _npm_command()
    log_dir = OBS_LOCAL_ROOT / "data" / "logs"

    backend_status = "already_running" if _port_open(backend_host, backend_port) else "starting"
    frontend_status = "already_running" if _port_open(frontend_host, frontend_port) else "starting"
    backend_pid: int | None = None
    frontend_pid: int | None = None

    if backend_status == "starting":
        backend_process = _start_process(
            command=[
                runtime_python,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                backend_host,
                "--port",
                str(backend_port),
            ],
            cwd=OBS_LOCAL_ROOT,
            stdout_path=log_dir / "obs-local-backend.stdout.log",
            stderr_path=log_dir / "obs-local-backend.stderr.log",
        )
        backend_pid = backend_process.pid
        if not _wait_for_http(backend_health_url, args.backend_timeout):
            raise RuntimeError(f"obs-local backend failed to become healthy: {backend_health_url}")

    if frontend_status == "starting":
        frontend_process = _start_process(
            command=[
                npm,
                "run",
                "dev",
                "--",
                "--host",
                frontend_host,
                "--port",
                str(frontend_port),
            ],
            cwd=OBS_FRONTEND_ROOT,
            stdout_path=log_dir / "obs-local-frontend.stdout.log",
            stderr_path=log_dir / "obs-local-frontend.stderr.log",
        )
        frontend_pid = frontend_process.pid
        if not _wait_for_http(frontend_url, args.frontend_timeout):
            raise RuntimeError(f"obs-local frontend failed to become ready: {frontend_url}")

    payload = {
        "status": "ready",
        "backend": {
            "url": backend_url,
            "health_url": backend_health_url,
            "status": backend_status,
            "pid": backend_pid,
        },
        "frontend": {
            "url": frontend_url,
            "status": frontend_status,
            "pid": frontend_pid,
        },
        "logs": {
            "backend_stdout": str((log_dir / "obs-local-backend.stdout.log").resolve()),
            "backend_stderr": str((log_dir / "obs-local-backend.stderr.log").resolve()),
            "frontend_stdout": str((log_dir / "obs-local-frontend.stdout.log").resolve()),
            "frontend_stderr": str((log_dir / "obs-local-frontend.stderr.log").resolve()),
        },
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
