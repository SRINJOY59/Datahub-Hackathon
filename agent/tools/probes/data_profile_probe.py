"""Data-profile probe — profiles the asset and its upstream source tables,
classifies each numeric column's anomaly, and returns grounded Evidence.

This is the workhorse for data incidents: it does not need perfect column-level
lineage, only the (reliable) table lineage, and it finds the anomalous column by
profiling real data.
"""
from __future__ import annotations

from agent.contracts import ChangeType, ContextBundle, Evidence, Incident
from agent.registry import probe
from agent.tools.graph.column_lineage import ColumnLineageTool
from agent.tools.warehouse.profiler import ColumnProfiler, classify

_DATA_SIGNALS = {"assertion_failure", "schema_change", "freshness", "model_drift"}
_MAX_PROFILE_TABLES = 15  # cap work on very long pipelines


@probe
class DataProfileProbe:
    name = "data_profile"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.profiler = ColumnProfiler()
        self.lineage = ColumnLineageTool(gms_server)

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _DATA_SIGNALS

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        full_path = self.lineage.table_upstream_path(incident.asset_urn)  # self..source
        depth = {t: i for i, t in enumerate(full_path)}
        # On long pipelines, profile the failing asset + the deepest (source)
        # tables — the root cause originates upstream, so sources matter most.
        if len(full_path) > _MAX_PROFILE_TABLES:
            tables = full_path[:1] + full_path[-(_MAX_PROFILE_TABLES - 1):]
        else:
            tables = full_path
        evidence: list[Evidence] = []
        for table in tables:
            for col in self.profiler.numeric_columns(table):
                prof = self.profiler.profile_column(table, col)
                change, note = classify(prof)
                if change is ChangeType.UNKNOWN:
                    continue
                evidence.append(Evidence(
                    probe=self.name,
                    kind=change.value,
                    summary=f"{table}.{col}: {note} -> {change.value}",
                    data={
                        "table": table,
                        "column": col,
                        "change_type": change.value,
                        "depth": depth.get(table, 0),
                        "recent_mean": prof.recent_mean,
                        "mean": prof.mean,
                        "recent_null_rate": prof.recent_null_rate,
                    },
                    confidence="high",
                ))
        return evidence
