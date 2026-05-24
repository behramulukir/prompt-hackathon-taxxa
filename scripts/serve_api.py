"""Boot the FastAPI sidecar that backs the Next.js frontend.

    python -m scripts.serve_api                # defaults to :8000
    python -m scripts.serve_api --port 8001
    python -m scripts.serve_api --reload       # dev: auto-reload on edit

The frontend at ``lex-atlas-frontend/`` proxies to whatever URL is in
``AGENT_SIDECAR_URL`` (default ``http://localhost:8000``). Falls back to
its built-in fixture replay when this sidecar is unreachable, so the UI
never dead-ends — but you want the real pipeline running for the demo.
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    p.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on source change. Dev only — disables the in-process pipeline cache on each reload.",
    )
    args = p.parse_args()

    try:
        import uvicorn
    except ImportError:
        sys.stderr.write(
            "uvicorn is not installed. Install with:\n"
            "    pip install fastapi uvicorn[standard]\n"
            "  or (project-wide): uv add fastapi 'uvicorn[standard]'\n"
        )
        return 1

    uvicorn.run(
        "src.api.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
