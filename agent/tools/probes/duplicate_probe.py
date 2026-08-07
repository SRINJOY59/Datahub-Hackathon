"""Probe: where the duplicates entered the pipeline.

A re-delivered batch trips the uniqueness assertion wherever the key is tested,
which is usually somewhere in the middle of the pipeline rather than at the door
it came through. Counting duplicate keys per table and ranking by how far
upstream each sits points at the delivery itself, so the fix is applied once at
the source instead of repeatedly downstream.
"""
from __future__ import annotations

from agent.contracts import ContextBundle, Evidence, Incident
from agent.registry import probe
from agent.tools.graph.column_lineage import ColumnLineageTool
from agent.tools.graph.urns import sibling_dataset_urn
from agent.tools.warehouse.duck import connect
from ml.config import DUCKDB_PATH

_DUPLICATE_SIGNALS = {"assertion_failure", "volume_anomaly"}

# The column that should be unique per table, mirroring the dbt `unique` tests.
KEYS = {
    "raw_transactions": "transaction_id",
    "stg_transactions": "transaction_id",
    "training_dataset": "transaction_id",
    "feat_user_txn_stats": "user_id",
    "feat_merchant_risk": "merchant_id",
}


@probe
class DuplicateProbe:
    name = "duplicates"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.lineage = ColumnLineageTool(gms_server)

    def applies_to(self, incident: Incident) -> bool:
        return incident.signal_type.value in _DUPLICATE_SIGNALS

    def investigate(self, incident: Incident, context: ContextBundle) -> list[Evidence]:
        evidence: list[Evidence] = []
        con = connect(str(DUCKDB_PATH), read_only=True)
        try:
            for table, key in KEYS.items():
                counts = self._duplicate_count(con, table, key)
                if counts is None:
                    continue
                total, distinct = counts
                if total == distinct:
                    continue
                urn = sibling_dataset_urn(incident.asset_urn, table) \
                    if incident.asset_urn.startswith("urn:li:dataset:") else None
                evidence.append(Evidence(
                    probe=self.name,
                    kind="duplicate_records",
                    summary=(f"{table}: {total - distinct} duplicate {key} value(s) "
                             f"({total} rows, {distinct} distinct)"),
                    data={
                        "table": table,
                        "column": key,
                        "dataset_urn": urn,
                        "change_type": "duplicate_records",
                        "depth": self.lineage.source_depth(urn) if urn else 0,
                        "duplicates": total - distinct,
                    },
                    confidence="high",
                ))
        finally:
            con.close()
        return evidence

    @staticmethod
    def _duplicate_count(con, table: str, key: str) -> tuple[int, int] | None:
        try:
            row = con.execute(
                f'select count(*), count(distinct "{key}") from main."{table}"'
            ).fetchone()
        except Exception:
            return None
        return (int(row[0]), int(row[1])) if row else None
