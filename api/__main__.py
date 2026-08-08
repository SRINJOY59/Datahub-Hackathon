"""python -m api — the dashboard read API on its own, no webhooks required.

For the combined process (webhooks + this API on one port), use
`python -m agent serve` instead.
"""
from __future__ import annotations

import uvicorn

from api.server import GRAPHQL_PATH, create_app

DEFAULT_PORT = 8091


def main() -> None:
    app = create_app()
    print(f"\nSentinel Dashboard API on http://127.0.0.1:{DEFAULT_PORT}{GRAPHQL_PATH}\n")
    uvicorn.run(app, host="127.0.0.1", port=DEFAULT_PORT, log_level="info")


if __name__ == "__main__":
    main()
