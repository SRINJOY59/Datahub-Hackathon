"""Detector: external dependency / API breaking changes ("self-maintaining APIs").

Reads vendor advisories (a provider's announcement of a breaking change) from
.sentinel/advisories/*.json. For each advisory whose package is actually used in
the codebase, it emits an incident targeting the impacted DataHub asset — so a
`transformers`/`sklearn`/vendor-SDK change is traced to the ML model it breaks.

This is the trigger for the auto-fix flow: detect the breaking change, scan the
customer codebase, and open a PR — instead of just announcing it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.contracts import Incident, SignalType
from agent.registry import detector
from memory.codebase import CodebaseMemory

ADVISORIES_DIR = Path(__file__).resolve().parents[3] / ".sentinel" / "advisories"


def _installed_version(package: str) -> str | None:
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version(package)
        except PackageNotFoundError:
            return None
    except Exception:
        return None


@detector
class DependencyChangeDetector:
    name = "dependency_advisories"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.codebase = CodebaseMemory()

    def detect(self) -> list[Incident]:
        if not ADVISORIES_DIR.exists():
            return []
        incidents: list[Incident] = []
        for path in sorted(ADVISORIES_DIR.glob("*.json")):
            try:
                adv = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue

            import_name = adv.get("import_name", adv.get("package", ""))
            symbols = adv.get("symbols", []) or [import_name]
            usages = self.codebase.usages(symbols)
            if not usages:  # advisory doesn't affect this codebase
                continue

            impacted = self.codebase.impacted_assets(import_name)
            asset_urn = impacted[0] if impacted else \
                f"urn:li:dataPlatform:(external,{adv.get('package')})"

            incidents.append(Incident(
                id=f"DEP-{path.stem[:8]}",
                asset_urn=asset_urn,
                signal_type=SignalType.DEPENDENCY_CHANGE,
                detected_at=datetime.now(timezone.utc),
                summary=(f"{adv.get('package')} {adv.get('from_version')} -> "
                         f"{adv.get('to_version')}: {adv.get('summary')} "
                         f"({len(usages)} usage(s) in codebase)"),
                raw_evidence={
                    "advisory": adv,
                    "installed_version": _installed_version(adv.get("package", "")),
                    "usages": [{"file": u.file, "line": u.line_no, "code": u.line}
                               for u in usages],
                    "impacted_assets": impacted,
                },
            ))
        return incidents
