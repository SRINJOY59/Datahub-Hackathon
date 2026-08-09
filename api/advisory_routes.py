"""REST endpoints for Vendor Advisories and Dependency SRE workflows.

Endpoints:
- POST /api/v1/advisory: Ingests breaking-change advisories from API vendors.
- GET  /api/v1/advisory: Lists currently registered advisories.
- POST /api/v1/dependencies/scan: Triggers an immediate codebase dependency scan.
- GET  /api/v1/dependencies: Returns codebase dependencies and their status.
- GET  /api/v1/dependencies/blast-radius: Computes blast radius for a given package.
"""
from __future__ import annotations

from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api import api_health

router = APIRouter(prefix="/api/v1", tags=["Self-Maintaining APIs"])


class AdvisoryPayload(BaseModel):
    package: str = Field(..., description="Package or vendor SDK name, e.g. scikit-learn, stripe, twilio")
    import_name: Optional[str] = Field(None, description="Import name if different from package, e.g. sklearn")
    from_version: Optional[str] = Field("unknown", description="Version from which change applies")
    to_version: Optional[str] = Field("unknown", description="Target version containing the breaking change")
    kind: Optional[str] = Field("breaking_change", description="Type of change: breaking_change, deprecation, feature")
    summary: str = Field(..., description="Summary of the API breaking change or migration")
    migration: Optional[str] = Field("", description="Detailed instructions for the automated migration")
    symbols: Optional[list[str]] = Field(default_factory=list, description="Symbols affected by this change")
    source: Optional[str] = Field("webhook", description="Advisory origin: vendor_webhook, pypi, security_advisory")


@router.post("/advisory")
def post_advisory(payload: AdvisoryPayload):
    """Webhook endpoint for API vendors and package registries to publish breaking change notices."""
    result = api_health.ingest_advisory(payload.model_dump())
    if not result.get("accepted"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to ingest advisory"))
    return result


@router.get("/advisories")
def get_advisories():
    """List all registered vendor advisories."""
    return {"advisories": api_health.list_advisories()}


@router.post("/advisories/sync-registry")
def sync_registry():
    """Automatically monitor PyPI / GitHub releases for package updates and breaking changes."""
    return api_health.sync_registries()


@router.post("/dependencies/scan")
def trigger_scan():
    """Trigger an immediate SRE scan of codebase dependencies against active advisories."""
    return api_health.trigger_dependency_scan()


@router.get("/dependencies")
def get_dependencies(force: bool = False):
    """List all packages used across the codebase and their current status."""
    return {"dependencies": api_health.list_dependencies(force=force)}


@router.get("/dependencies/blast-radius")
def get_blast_radius(package: str = Query(..., description="Package name to trace")):
    """Compute the full DataHub lineage blast radius of an API / package change."""
    return api_health.dependency_blast_radius(package)


@router.get("/dependencies/stats")
def get_stats():
    """Summary metrics for the API Health & Self-Maintaining APIs dashboard."""
    return api_health.api_health_stats()
