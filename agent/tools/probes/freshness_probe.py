"""Probe: which table actually stopped, as opposed to which noticed.

When a feed stops, every table downstream of it looks equally stale — they are
all waiting on the same missing rows. Reporting them as a flat list would let the
RCA blame whichever happened to be listed first, usually a mart, which tells the
on-call nothing useful.

So each affected table is ranked by how far upstream it sits, and the deepest one
is the one the evidence points at. That is the feed someone has to go and fix.
"""
from __future__ import annotations

from agent.contracts import ContextBundle, Evidence, Incident
from agent.registry import probe
from agent.tools.graph.column_lineage import ColumnLineageTool
from agent.tools.graph.urns import sibling_dataset_urn

_FRESHNESS_SIGNALS = {"freshness"}


@probe
class FreshnessProbe:
    name = "freshness"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.lineage = ColumnLineageTool(gms_server)

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _FRESHNESS_SIGNALS

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        stale = (incident.raw_evidence or {}).get("stale_tables") or []
        if not stale:
            return []

        evidence: list[Evidence] = []
        for entry in stale:
            table = entry.get("table")
            if not table:
                continue
            urn = sibling_dataset_urn(incident.asset_urn, table)
            lag = entry.get("lag_hours", 0.0)
            lag_text = "no timestamped rows left" if lag == float("inf") \
                else f"{lag:.0f}h behind baseline"
            evidence.append(Evidence(
                probe=self.name,
                kind="freshness_lag",
                summary=(f"{table}: {lag_text} "
                         f"(newest {entry.get('actual')}, "
                         f"expected around {entry.get('expected')})"),
                data={
                    "table": table,
                    "dataset_urn": urn,
                    "change_type": "freshness_lag",
                    "depth": self.lineage.source_depth(urn),
                    "lag_hours": lag,
                },
                confidence="high",
            ))
        return evidence
