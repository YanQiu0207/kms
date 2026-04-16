from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_config, resolve_config_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe kms-api health endpoint.")
    parser.add_argument("--config", type=str, default=None, help="Optional config file path.")
    parser.add_argument("--host", type=str, default=None, help="Override host.")
    parser.add_argument("--port", type=int, default=None, help="Override port.")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout in seconds.")
    return parser.parse_args()


def _decode_json(raw: bytes) -> dict[str, object]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("response payload must be a JSON object")
    return payload


def main() -> int:
    args = parse_args()
    config_path = resolve_config_path(args.config)
    config = load_config(config_path)
    host = args.host or config.server.host
    port = args.port or config.server.port
    url = f"http://{host}:{port}/health"

    try:
        with urlopen(url, timeout=args.timeout) as response:
            payload = _decode_json(response.read())
            if response.status != 200 or payload.get("status") != "ok":
                print(
                    json.dumps(
                        {
                            "status": "unhealthy",
                            "url": url,
                            "status_code": response.status,
                            "payload": payload,
                        },
                        ensure_ascii=False,
                    )
                )
                return 1
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "http_error",
                    "url": url,
                    "status_code": exc.code,
                    "body": body,
                },
                ensure_ascii=False,
            )
        )
        return 1
    except (URLError, TimeoutError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "connection_failed",
                    "url": url,
                    "detail": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                "url": url,
                "service": payload.get("service"),
                "version": payload.get("version"),
                "timestamp": payload.get("timestamp"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
