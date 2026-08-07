"""DuckDB connections, with the one piece of care this setup requires.

DuckDB allows a single writer per file, and a process that has just exited can
hold the lock for a moment longer than it takes us to ask for it. Because the
agent's actuators run dbt in a subprocess and then immediately read or write the
same file, a naive connect() fails intermittently — the worst kind of failure,
since it looks like a real error and disappears on retry.

So every connection in the agent goes through here, and a lock conflict is
retried briefly before being treated as a genuine failure.
"""
from __future__ import annotations

import time
from pathlib import Path

import duckdb

CONNECT_RETRIES = 5
CONNECT_BACKOFF = 0.4  # seconds, linear


def connect(path: str | Path, read_only: bool = False,
            retries: int = CONNECT_RETRIES) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection, waiting out a transient lock from a dbt
    subprocess that is still shutting down. Raises the original error if the
    lock is still held after `retries` attempts — a lock that outlives the
    backoff is a real problem, not a race."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return duckdb.connect(str(path), read_only=read_only)
        except duckdb.IOException as e:
            if "used by another process" not in str(e) and "lock" not in str(e).lower():
                raise
            last = e
            if attempt < retries - 1:
                time.sleep(CONNECT_BACKOFF * (attempt + 1))
    raise last if last else RuntimeError("could not connect to DuckDB")
