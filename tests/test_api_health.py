"""Tests for the Self-Maintaining APIs & Dependency Health module."""
from __future__ import annotations

import json
from pathlib import Path
from api import api_health


def test_list_dependencies():
    deps = api_health.list_dependencies(force=True)
    assert isinstance(deps, list)
    assert len(deps) > 0

    packages = {d["package"] for d in deps}
    # Standard packages used in repo
    assert "datahub" in packages or "pydantic" in packages or "fastapi" in packages


def test_api_health_stats():
    stats = api_health.api_health_stats()
    assert "total_dependencies" in stats
    assert "at_risk" in stats
    assert "healthy" in stats
    assert stats["total_dependencies"] >= 0


def test_blast_radius_computation():
    radius = api_health.dependency_blast_radius("scikit-learn")
    assert radius["package"] == "scikit-learn"
    assert "files" in radius
    assert "direct_assets" in radius
    assert "downstream_assets" in radius


def test_ingest_and_scan_advisory(tmp_path, monkeypatch):
    # Point ADVISORIES_DIR to a temporary path
    temp_advisories = tmp_path / "advisories"
    monkeypatch.setattr(api_health, "ADVISORIES_DIR", temp_advisories)

    payload = {
        "package": "test-sdk",
        "import_name": "test_sdk",
        "from_version": "1.0.0",
        "to_version": "2.0.0",
        "summary": "Breaking change in Client.connect()",
        "migration": "Pass host parameter explicitly",
        "symbols": ["Client", "connect"],
    }

    res = api_health.ingest_advisory(payload)
    assert res["accepted"] is True
    assert (temp_advisories / f"{res['advisory_id']}.json").exists()

    advisories = api_health.list_advisories()
    assert len(advisories) == 1
    assert advisories[0]["package"] == "test-sdk"


def test_registry_monitor_sync(tmp_path, monkeypatch):
    from agent.tools.detectors.registry_monitor import RegistryMonitor
    import agent.tools.detectors.registry_monitor as rm_mod

    temp_advisories = tmp_path / "advisories"
    monkeypatch.setattr(rm_mod, "ADVISORIES_DIR", temp_advisories)
    monkeypatch.setattr(api_health, "ADVISORIES_DIR", temp_advisories)

    monitor = RegistryMonitor(timeout_seconds=1.0)
    res = monitor.scan_and_sync(packages=["scikit-learn"])
    assert res["success"] is True
    assert res["packages_checked"] == 1
    assert res["advisories_generated"] >= 1
    assert len(list(temp_advisories.glob("*.json"))) >= 1
