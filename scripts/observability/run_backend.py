"""Start the normal backend with local tracing and an explicitly selected test DB."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="Use a test database or an intentional test copy",
    )
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--collector", default="http://127.0.0.1:6006/v1/traces")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend"))
    database = args.database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()
    from live_capture import (
        TraceRequests,
        configure,
        instrument_httpx,
        instrument_workspace,
    )

    provider = configure(args.collector)
    restore_http = instrument_httpx()
    restore_tools = instrument_workspace()
    import uvicorn
    from app.main import app

    try:
        app.add_middleware(TraceRequests)
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    finally:
        restore_tools()
        restore_http()
        provider.shutdown()


if __name__ == "__main__":
    main()
