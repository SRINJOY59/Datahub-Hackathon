"""Probe: where the rows went missing, and by how much.

Row counts are the one thing this pipeline's tests never look at, so when volume
moves there is no assertion output to read — only the counts themselves. Each
affected table is compared against its healthy baseline and ranked by how far
upstream it sits, so the RCA blames the delivery that shrank rather than the
mart that inherited the shortfall.
"""
from __future__ import annotations

from agent.contracts import ContextBundle, Evidence, Incident
from agent.registry import probe
from agent.tools.graph.column_lineage import ColumnLineageTool
from agent.tools.graph.urns import sibling_dataset_urn

_VOLUME_SIGNALS = {"volume_anomaly"}


@probe
class VolumeProbe:
    name = "volume"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.lineage = ColumnLineageTool(gms_server)

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _VOLUME_SIGNALS

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        anomalies = (incident.raw_evidence or {}).get("volume_anomalies") or []
        if not anomalies:
            return []

        evidence: list[Evidence] = []
        for entry in anomalies:
            table = entry.get("table")
            if not table:
                continue
            urn = sibling_dataset_urn(incident.asset_urn, table)
            shift = entry.get("shift", 0.0)
            evidence.append(Evidence(
                probe=self.name,
                kind="volume_anomaly",
                summary=(f"{table}: {entry.get('actual')} rows vs "
                         f"{entry.get('expected')} baseline ({shift:+.0%})"),
                data={
                    "table": table,
                    "dataset_urn": urn,
                    "change_type": "volume_anomaly",
                    "depth": self.lineage.source_depth(urn),
                    "shift": shift,
                    "expected": entry.get("expected"),
                    "actual": entry.get("actual"),
                },
                confidence="high",
            ))
        return evidence
