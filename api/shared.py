"""Shared utilities for the API layer.

Consolidates helpers that were duplicated across api_health.py, insights.py,
and registry_monitor.py: GMS URL lookup, installed-package version retrieval,
the repo root path, and a simple time-based cache.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Generic, Optional, TypeVar

T = TypeVar("T")

# One computation, used everywhere that needs to locate .sentinel/ or examples/.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
ADVISORIES_DIR: Path = REPO_ROOT / ".sentinel" / "advisories"
FIXES_DIR: Path = REPO_ROOT / "examples" / "generated_fixes"


def gms_url() -> str:
    """DataHub GMS base URL, from the environment or the local-quickstart default."""
    return os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")


def installed_version(package: str) -> Optional[str]:
    """Return the installed version of *package*, or None if not installed."""
    try:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as _version

        return _version(package)
    except Exception:
        return None


class TTLCache(Generic[T]):
    """A trivially simple, single-value, time-based cache.

    Replaces the bare ``(float, list[dict]) | None`` tuples that were used
    as module-level caches in api_health and insights.  Thread-safe for
    the single-writer / many-reader pattern our API uses.
    """

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._stamp: float = 0.0
        self._value: Optional[T] = None

    def get(self) -> Optional[T]:
        if self._value is not None and (time.monotonic() - self._stamp) < self._ttl:
            return self._value
        return None

    def set(self, value: T) -> None:
        self._value = value
        self._stamp = time.monotonic()

    def get_or_compute(self, fn: Callable[[], T]) -> T:
        """Return the cached value, or call *fn* to produce a fresh one."""
        cached = self.get()
        if cached is not None:
            return cached
        fresh = fn()
        self.set(fresh)
        return fresh

    def invalidate(self) -> None:
        self._stamp = 0.0
