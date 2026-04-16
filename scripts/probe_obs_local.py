from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
OBS_LOCAL_ROOT = ROOT / "obs-local"
DEFAULT_CONFIG_PATH = OBS_LOCAL_ROOT / "config.yaml"


def _load_obs_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"obs-local config must be a mapping: {path}")
    return payload


def _port_open(host: str, port: int, timeout: float) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe obs-local backend health endpoint.")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH), help="Path to obs-local config.yaml.")
    parser.add_argument("--host", type=str, default=None, help="Override backend host.")
    parser.add_argument("--port", type=int, default=None, help="Override backend port.")
    parser.add_argument("--frontend-host", type=str, default="127.0.0.1", help="Frontend host.")
    parser.add_argument("--frontend-port", type=int, default=4174, help="Frontend port.")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP/TCP timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = _load_obs_config(config_path)

    server = config.get("server") if isinstance(config.get("server"), dict) else {}
    host = args.host or str(server.get("host") or "127.0.0.1")
    port = args.port or int(server.get("port") or 49154)
    frontend_host = args.frontend_host
    frontend_port = args.frontend_port
    backend_url = f"http://{host}:{port}/api/health"

    try:
        with urlopen(backend_url, timeout=args.timeout) as response:
            raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("response payload must be a JSON object")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"status": "error", "reason": "http_error", "url": backend_url,
                          "status_code": exc.code, "body": body}, ensure_ascii=False))
        return 1
    except (URLError, TimeoutError, ValueError) as exc:
        print(json.dumps({"status": "error", "reason": "connection_failed", "url": backend_url,
                          "detail": str(exc)}, ensure_ascii=False))
        return 1

    service = payload.get("service") or {}
    service_status = str(service.get("status") or "")
    frontend_up = _port_open(frontend_host, frontend_port, args.timeout)

    if service_status == "error":
        overall = "unhealthy"
        exit_code = 1
    elif service_status in {"ok", "degraded"}:
        overall = "ok" if (service_status == "ok" and frontend_up) else "degraded"
        exit_code = 0
    else:
        overall = "unknown"
        exit_code = 1

    print(json.dumps({
        "status": overall,
        "backend": {
            "url": backend_url,
            "service": service.get("service"),
            "status": service_status,
            "version": service.get("version"),
            "started_at": service.get("started_at"),
            "replaying": service.get("replaying"),
        },
        "frontend": {
            "host": frontend_host,
            "port": frontend_port,
            "reachable": frontend_up,
        },
        "generated_at": payload.get("generated_at"),
    }, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
