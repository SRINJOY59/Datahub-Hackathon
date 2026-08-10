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

# Base workspace computation
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
_ACTIVE_REPO_PATH: Path = REPO_ROOT
_ACTIVE_REPO_ID: str = "default"

def get_active_repo_root() -> Path:
    """Return the active repository's filesystem root."""
    global _ACTIVE_REPO_PATH, _ACTIVE_REPO_ID
    if _ACTIVE_REPO_PATH == REPO_ROOT:
        try:
            from api.repo_onboarding import ConnectedRepoStore
            active = ConnectedRepoStore().get_active()
            if active and Path(active["repo_path"]).exists():
                _ACTIVE_REPO_PATH = Path(active["repo_path"])
                _ACTIVE_REPO_ID = active["repo_name"]
        except Exception:
            pass
    return _ACTIVE_REPO_PATH if _ACTIVE_REPO_PATH.exists() else REPO_ROOT


def get_active_repo_id() -> str:
    """Return the active repository identifier."""
    global _ACTIVE_REPO_ID, _ACTIVE_REPO_PATH
    if _ACTIVE_REPO_ID == "default":
        try:
            from api.repo_onboarding import ConnectedRepoStore
            active = ConnectedRepoStore().get_active()
            if active:
                _ACTIVE_REPO_ID = active["repo_name"]
                _ACTIVE_REPO_PATH = Path(active["repo_path"])
        except Exception:
            pass
    return _ACTIVE_REPO_ID


def set_active_repo(repo_id: str, repo_path: Path | str) -> None:
    """Switch the active repository context across all Sentinel services."""
    global _ACTIVE_REPO_ID, _ACTIVE_REPO_PATH
    _ACTIVE_REPO_ID = repo_id
    _ACTIVE_REPO_PATH = Path(repo_path).resolve()

def get_active_repo_urns() -> list[str]:
    """Return entity URNs for the active repo, or empty if scoping doesn't apply.

    Returns empty (meaning "show everything") when:
    - No repos are onboarded yet
    - Only one repo exists (no ambiguity)
    - The active repo is the default workspace or its path matches REPO_ROOT
    """
    try:
        from api.repo_onboarding import ConnectedRepoStore, _extract_entities
        store = ConnectedRepoStore()
        all_repos = store.list()
        if len(all_repos) <= 1:
            return []
        active = store.get_active()
        if not active or active.get("id") == "default":
            return []
        if Path(active.get("repo_path", "")).resolve() == REPO_ROOT:
            return []
        entities = _extract_entities(active.get("lineage_json"))
        return [e["urn"] for e in entities if e.get("urn")]
    except Exception:
        pass
    return []


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
