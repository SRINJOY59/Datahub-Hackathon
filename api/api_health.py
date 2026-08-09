"""Read-side adapters for the Self-Maintaining APIs feature.

Surfaces dependency health, active advisories, migration history, and
lineage-traced blast radius — the data the /api-health dashboard page needs.

Design mirrors insights.py: everything degrades to an empty result if DataHub
is down, and heavyweight computations are cached behind a short TTL.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
ADVISORIES_DIR = REPO_ROOT / ".sentinel" / "advisories"
FIXES_DIR = REPO_ROOT / "examples" / "generated_fixes"

_DEP_TTL_SECONDS = 30.0
_dep_cache: tuple[float, list[dict]] | None = None


def _gms() -> str:
    return os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")


# --------------------------------------------------------------------------- #
# Dependencies — what packages the codebase uses
# --------------------------------------------------------------------------- #
def list_dependencies(force: bool = False) -> list[dict]:
    """Every top-level package imported in the codebase, with version info."""
    global _dep_cache
    now = time.monotonic()
    if not force and _dep_cache and (now - _dep_cache[0]) < _DEP_TTL_SECONDS:
        return _dep_cache[1]

    try:
        from memory.codebase import shared_codebase
        cb = shared_codebase()
        packages = sorted(cb.all_packages())
    except Exception:
        return _dep_cache[1] if _dep_cache else []

    rows: list[dict] = []
    for pkg in packages:
        version = _installed_version(pkg)
        files = cb.files_importing(pkg)
        assets = cb.impacted_assets(pkg)
        has_advisory = _has_active_advisory(pkg)
        rows.append({
            "package": pkg,
            "installed_version": version,
            "files_using": len(files),
            "impacted_assets": len(assets),
            "asset_urns": assets[:5],
            "has_advisory": has_advisory,
            "status": "at_risk" if has_advisory else ("healthy" if version else "unknown"),
        })

    # Sort: at_risk first, then by file count descending
    rows.sort(key=lambda r: (0 if r["status"] == "at_risk" else 1, -r["files_using"]))
    _dep_cache = (now, rows)
    return rows


def _installed_version(package: str) -> str | None:
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version(package)
        except PackageNotFoundError:
            return None
    except Exception:
        return None


def _has_active_advisory(package: str) -> bool:
    if not ADVISORIES_DIR.exists():
        return False
    for path in ADVISORIES_DIR.glob("*.json"):
        try:
            adv = json.loads(path.read_text(encoding="utf-8"))
            if adv.get("package") == package:
                return True
        except (OSError, ValueError):
            continue
    return False


# --------------------------------------------------------------------------- #
# Advisories — active vendor breaking-change notices
# --------------------------------------------------------------------------- #
def list_advisories() -> list[dict]:
    """Every active advisory in .sentinel/advisories/, enriched with usage data."""
    if not ADVISORIES_DIR.exists():
        return []

    try:
        from memory.codebase import shared_codebase
        cb = shared_codebase()
    except Exception:
        cb = None

    rows: list[dict] = []
    for path in sorted(ADVISORIES_DIR.glob("*.json")):
        try:
            adv = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        # Enrich with codebase usage
        import_name = adv.get("import_name", adv.get("package", ""))
        symbols = adv.get("symbols", []) or [import_name]
        usages: list[dict] = []
        impacted_assets: list[str] = []
        if cb:
            raw_usages = cb.usages(symbols)
            usages = [{"file": u.file, "line": u.line_no, "code": u.line}
                      for u in raw_usages[:20]]
            impacted_assets = cb.impacted_assets(import_name)

        rows.append({
            "id": path.stem,
            "package": adv.get("package", ""),
            "import_name": import_name,
            "from_version": adv.get("from_version", ""),
            "to_version": adv.get("to_version", ""),
            "kind": adv.get("kind", "breaking_change"),
            "summary": adv.get("summary", ""),
            "migration": adv.get("migration", ""),
            "symbols": symbols,
            "usages": usages,
            "usages_count": len(usages),
            "impacted_assets": impacted_assets,
            "impacted_count": len(impacted_assets),
            "published_at": adv.get("published_at",
                                    datetime.now(timezone.utc).isoformat()),
        })

    return rows


# --------------------------------------------------------------------------- #
# Migration history — auto-applied fixes from the codefix tool
# --------------------------------------------------------------------------- #
def migration_history() -> list[dict]:
    """Resolved dependency-change incidents + their generated diffs/PRs."""
    rows: list[dict] = []

    # Read from the incident store
    try:
        from agent.store import shared_store
        store = shared_store()
        all_incidents = store.list(limit=200)
        dep_incidents = [r for r in all_incidents
                         if r.get("change_type") == "dependency_change"]
    except Exception:
        dep_incidents = []

    for inc in dep_incidents:
        diff_path = FIXES_DIR / f"{inc['id']}.diff"
        diff_content = ""
        if diff_path.exists():
            try:
                diff_content = diff_path.read_text(encoding="utf-8")
            except OSError:
                pass

        rows.append({
            "incident_id": inc["id"],
            "asset_urn": inc.get("asset_urn", ""),
            "asset_name": inc.get("asset_name"),
            "status": inc.get("status", "open"),
            "resolved": inc.get("resolved", False),
            "pr": inc.get("pr"),
            "cost_usd": inc.get("cost_usd"),
            "narrative": inc.get("narrative", ""),
            "detected_at": inc.get("detected_at", ""),
            "closed_at": inc.get("closed_at"),
            "has_diff": bool(diff_content),
            "diff_preview": diff_content[:2000] if diff_content else "",
        })

    rows.sort(key=lambda r: r.get("detected_at", ""), reverse=True)
    return rows


# --------------------------------------------------------------------------- #
# Blast radius — lineage-traced impact of a dependency change
# --------------------------------------------------------------------------- #
def dependency_blast_radius(package: str) -> dict:
    """Trace how a package change fans out through the DataHub lineage graph."""
    result: dict[str, Any] = {
        "package": package,
        "files": [],
        "direct_assets": [],
        "downstream_assets": [],
        "total_impacted": 0,
    }

    try:
        from memory.codebase import shared_codebase
        cb = shared_codebase()
    except Exception:
        return result

    files = cb.files_importing(package)
    result["files"] = files[:20]

    direct_assets = cb.impacted_assets(package)
    result["direct_assets"] = direct_assets

    # Try to read downstream from DataHub lineage
    downstream: list[dict] = []
    try:
        from agent.tools.graph.context import read_context
        for urn in direct_assets:
            ctx = read_context(urn, _gms())
            for node in ctx.downstream:
                downstream.append({
                    "urn": node.urn,
                    "name": node.name,
                    "entity_type": node.entity_type,
                    "upstream_of": urn,
                })
    except Exception:
        pass

    # Deduplicate downstream by urn
    seen = set(direct_assets)
    unique_downstream = []
    for d in downstream:
        if d["urn"] not in seen:
            seen.add(d["urn"])
            unique_downstream.append(d)

    result["downstream_assets"] = unique_downstream
    result["total_impacted"] = len(direct_assets) + len(unique_downstream)
    return result


# --------------------------------------------------------------------------- #
# SRE: trigger a dependency scan
# --------------------------------------------------------------------------- #
def trigger_dependency_scan() -> dict:
    """Run the dependency detector now and return what it found."""
    try:
        from agent.tools.detectors.dependency import DependencyChangeDetector
        det = DependencyChangeDetector()
        incidents = det.detect()
        return {
            "scanned": True,
            "advisories_checked": len(list(ADVISORIES_DIR.glob("*.json"))
                                      ) if ADVISORIES_DIR.exists() else 0,
            "incidents_found": len(incidents),
            "incidents": [
                {
                    "id": inc.id,
                    "asset_urn": inc.asset_urn,
                    "summary": inc.summary,
                }
                for inc in incidents
            ],
        }
    except Exception as e:
        return {
            "scanned": False,
            "error": str(e),
            "advisories_checked": 0,
            "incidents_found": 0,
            "incidents": [],
        }


# --------------------------------------------------------------------------- #
# SRE: sync with PyPI / npm / GitHub registries
# --------------------------------------------------------------------------- #
def sync_registries(packages: Optional[list[str]] = None) -> dict:
    """Automatically monitor PyPI/GitHub for package updates & breaking changes."""
    try:
        from agent.tools.detectors.registry_monitor import shared_registry_monitor
        monitor = shared_registry_monitor()
        return monitor.scan_and_sync(packages=packages)
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "packages_checked": 0,
            "advisories_generated": 0,
            "network_online": False,
            "generated": [],
        }


# --------------------------------------------------------------------------- #
# Vendor webhook: ingest an advisory from an external source
# --------------------------------------------------------------------------- #
def ingest_advisory(payload: dict) -> dict:
    """Validate and persist a vendor advisory from a webhook POST.

    This is the industry-standard pattern (like Dependabot): vendors push
    breaking-change notices to a webhook; the agent picks them up on the
    next detection sweep.
    """
    required = {"package", "summary"}
    missing = required - set(payload.keys())
    if missing:
        return {"accepted": False, "error": f"missing fields: {missing}"}

    ADVISORIES_DIR.mkdir(parents=True, exist_ok=True)

    # Generate a stable ID from the package + version
    from_v = payload.get("from_version", "unknown")
    to_v = payload.get("to_version", "unknown")
    adv_id = f"{payload['package']}-{from_v}-{to_v}".replace(".", "_")

    # Enrich with defaults
    adv = {
        "package": payload["package"],
        "import_name": payload.get("import_name", payload["package"]),
        "from_version": from_v,
        "to_version": to_v,
        "kind": payload.get("kind", "breaking_change"),
        "summary": payload["summary"],
        "migration": payload.get("migration", ""),
        "symbols": payload.get("symbols", []),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "source": payload.get("source", "webhook"),
    }

    path = ADVISORIES_DIR / f"{adv_id}.json"
    path.write_text(json.dumps(adv, indent=2), encoding="utf-8")

    try:
        rel_path = str(path.relative_to(REPO_ROOT))
    except ValueError:
        rel_path = str(path)

    return {
        "accepted": True,
        "advisory_id": adv_id,
        "path": rel_path,
    }


# --------------------------------------------------------------------------- #
# Summary stats for the API health page header
# --------------------------------------------------------------------------- #
def api_health_stats() -> dict:
    """Aggregate stats for the API health dashboard."""
    deps = list_dependencies()
    advisories = list_advisories()
    migrations = migration_history()

    total_deps = len(deps)
    at_risk = sum(1 for d in deps if d["status"] == "at_risk")
    active_advisories = len(advisories)
    resolved_migrations = sum(1 for m in migrations if m["resolved"])
    pending_migrations = sum(1 for m in migrations if not m["resolved"])
    total_usages = sum(a.get("usages_count", 0) for a in advisories)

    return {
        "total_dependencies": total_deps,
        "at_risk": at_risk,
        "healthy": total_deps - at_risk,
        "active_advisories": active_advisories,
        "resolved_migrations": resolved_migrations,
        "pending_migrations": pending_migrations,
        "total_affected_usages": total_usages,
    }
