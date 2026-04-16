from __future__ import annotations

import argparse

import uvicorn

from app.config import load_config
from app.main import create_app
from app.observability import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="启动指定配置的本地 KMS API 服务")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--host", default="", help="可选：覆盖监听 host")
    parser.add_argument("--port", type=int, default=0, help="可选：覆盖监听 port")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.host:
        config.server.host = args.host
    if args.port > 0:
        config.server.port = args.port

    configure_logging()
    app = create_app(config)
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        reload=False,
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
