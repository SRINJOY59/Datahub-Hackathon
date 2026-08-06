"""Column-lineage probe — reports the upstream table/column path from the failing
asset toward its source, as Evidence. Adds precision to the data-profile probe
(which column, how far upstream).
"""
from __future__ import annotations

from agent.contracts import ContextBundle, Evidence, Incident
from agent.registry import probe
from agent.tools.graph.column_lineage import ColumnLineageTool

_DATA_SIGNALS = {"assertion_failure", "schema_change", "model_drift"}


@probe
class ColumnLineageProbe:
    name = "column_lineage"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.lineage = ColumnLineageTool(gms_server)

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _DATA_SIGNALS

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        path = self.lineage.table_upstream_path(incident.asset_urn)
        if len(path) < 2:
            return []
        return [Evidence(
            probe=self.name,
            kind="lineage_path",
            summary="upstream table path: " + " <- ".join(path),
            data={"path": path, "source": path[-1]},
            confidence="high",
        )]
