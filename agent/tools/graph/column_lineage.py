"""Column-level lineage walk.

Given a failing column, traverse DataHub's fine-grained (column) lineage upstream
hop-by-hop to the source column — e.g.

    feat_user_txn_stats.avg_txn_amount
        <- stg_transactions.amount
            <- raw_transactions.amount   (source)

The dbt source emits fine-grained lineage on the dbt datasets, so we always read
the dbt dataset's aspect and normalize table identity by logical name (ignoring
the dbt/duckdb platform split).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import datahub.emitter.mce_builder as builder
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import UpstreamLineageClass

ENV = "PROD"
MAX_HOPS = 50  # supports long ML pipelines; cycle-safe via the `seen` set
_SF_RE = re.compile(r"urn:li:schemaField:\((urn:li:dataset:\(.+?\)),(.+)\)$")


@dataclass
class ColumnRef:
    table: str          # logical table name, e.g. "stg_transactions"
    column: str
    dataset_urn: str    # dbt dataset urn for the table


def _parse_schema_field(sf_urn: str) -> ColumnRef | None:
    m = _SF_RE.match(sf_urn)
    if not m:
        return None
    dataset_urn, column = m.group(1), m.group(2)
    # dataset name is the 2nd comma-separated token of the dataset urn body
    name = dataset_urn.split(",")[1]
    table = name.split(".")[-1]
    return ColumnRef(table=table, column=column, dataset_urn=dataset_urn)


class ColumnLineageTool:
    def __init__(self, gms_server: str | None = None) -> None:
        from agent.gms import default_gms_server

        gms_server = gms_server or default_gms_server()
        self.graph = DataHubGraph(DataHubGraphConfig(server=gms_server))

    def _dbt_urn(self, table: str, name_prefix: str) -> str:
        return builder.make_dataset_urn("dbt", f"{name_prefix}.{table}", ENV)

    def _upstreams_of(self, table: str, column: str, name_prefix: str) -> list[ColumnRef]:
        """Direct column-level upstreams of (table, column), via the dbt aspect."""
        urn = self._dbt_urn(table, name_prefix)
        up = self.graph.get_aspect(urn, UpstreamLineageClass)
        if not up or not up.fineGrainedLineages:
            return []
        found: dict[str, ColumnRef] = {}
        for fgl in up.fineGrainedLineages:
            downstream_cols = {
                r.column for r in map(_parse_schema_field, fgl.downstreams or []) if r
            }
            if column in downstream_cols:
                for ref in map(_parse_schema_field, fgl.upstreams or []):
                    if ref and ref.table != table:  # skip sibling self-maps
                        found[f"{ref.table}.{ref.column}"] = ref
        return list(found.values())

    def table_upstream_path(self, start_dataset_urn: str) -> list[str]:
        """Ordered logical-table path from the asset to its source(s), self first,
        source last. Table-level lineage is reliable even when column-level
        aggregation lineage isn't captured."""
        start_name = start_dataset_urn.split(",")[1]
        name_prefix = start_name.rsplit(".", 1)[0]
        start_table = start_name.split(".")[-1]

        order = [start_table]
        seen = {start_table}
        frontier = [start_table]
        for _ in range(MAX_HOPS):
            nxt: list[str] = []
            for tbl in frontier:
                up = self.graph.get_aspect(self._dbt_urn(tbl, name_prefix),
                                           UpstreamLineageClass)
                for u in (up.upstreams or []) if up else []:
                    name = u.dataset.split(",")[1].split(".")[-1]
                    if name not in seen and name != tbl:
                        seen.add(name)
                        order.append(name)
                        nxt.append(name)
            frontier = nxt
            if not nxt:
                break
        return order

    def source_depth(self, dataset_urn: str) -> int:
        """How source-like a table is — higher means further upstream.

        Used to rank several affected tables when the incident is table-level
        (a stopped feed, a halved batch) and there is no anomalous column to
        follow. A table with nothing upstream of it *is* the origin; one with a
        long ancestry is downstream of the problem, showing the same symptom
        second-hand. Counting ancestors and inverting gives that ordering without
        needing to know the pipeline's shape in advance.
        """
        try:
            return MAX_HOPS - len(self.table_upstream_path(dataset_urn))
        except Exception:
            return 0

    def upstream_path(self, start_dataset_urn: str, column: str) -> list[ColumnRef]:
        """Walk from (start dataset, column) to the source column. Returns the
        path as ColumnRefs, deepest (source) last."""
        start_name = start_dataset_urn.split(",")[1]        # e.g. fraud_demo.fraud.main.feat_user_txn_stats
        name_prefix = start_name.rsplit(".", 1)[0]          # fraud_demo.fraud.main
        start_table = start_name.split(".")[-1]

        path: list[ColumnRef] = [
            ColumnRef(start_table, column, self._dbt_urn(start_table, name_prefix))
        ]
        seen = {f"{start_table}.{column}"}
        frontier = (start_table, column)

        for _ in range(MAX_HOPS):  # depth guard
            ups = self._upstreams_of(frontier[0], frontier[1], name_prefix)
            # follow a single deterministic chain (first unseen upstream)
            nxt = next((r for r in ups if f"{r.table}.{r.column}" not in seen), None)
            if not nxt:
                break
            seen.add(f"{nxt.table}.{nxt.column}")
            path.append(nxt)
            frontier = (nxt.table, nxt.column)
        return path
