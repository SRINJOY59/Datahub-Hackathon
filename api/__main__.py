"""python -m api — the dashboard read API on its own, no webhooks required.

For the combined process (webhooks + this API on one port), use
`python -m agent serve` instead.
"""
from __future__ import annotations

import os
import uvicorn

from api.server import GRAPHQL_PATH, create_app

DEFAULT_PORT = 8091


def main() -> None:
    app = create_app()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    print(f"\nSentinel Dashboard API starting on http://{host}:{port}{GRAPHQL_PATH}\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
