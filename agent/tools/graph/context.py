"""DataHub-backed context tool — the real read side of the mechanism interface.

Reads lineage, schema, ownership, tags, and failing assertions from the graph,
and surfaces open incidents (datasets whose latest assertion run FAILED). This is
what gives the agent real understanding instead of guesses.
"""
from __future__ import annotations

from datetime import datetime, timezone

from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    AssertionInfoClass,
    GlobalTagsClass,
    OwnershipClass,
    SchemaMetadataClass,
)

from agent.contracts import (
    ContextBundle,
    Incident,
    LineageNode,
    SignalType,
)

_GQL_TYPE_TO_ENTITY = {
    "DATASET": "dataset",
    "MLMODEL": "mlModel",
    "MLMODEL_GROUP": "mlModelGroup",
    "MLMODEL_DEPLOYMENT": "mlModelDeployment",
    "DATA_JOB": "dataJob",
    "DATA_FLOW": "dataFlow",
}


def _short_name(urn: str) -> str:
    """Human-ish name from a urn tail, e.g. '...main.feat_user_txn_stats,PROD)'."""
    if urn.startswith("urn:li:dataset:"):
        body = urn.split(",")[1]
        return body.split(".")[-1]
    if urn.startswith(("urn:li:mlModel:", "urn:li:mlModelDeployment:",
                       "urn:li:mlModelGroup:")):
        return urn.split(",")[1]
    if urn.startswith("urn:li:dataJob:"):
        return urn.split(",")[-1].rstrip(")")
    return urn


class DataHubContextTool:
    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.graph = DataHubGraph(DataHubGraphConfig(server=gms_server))

    # ------------------------------------------------------------------ #
    # detection
    # ------------------------------------------------------------------ #
    def _assertion_name(self, assertion_urn: str) -> str:
        """Readable name for a dbt-test assertion (from its dbt_unique_id).

        dbt appends a uniqueness hash to generated tests, so the last segment is
        often meaningless — an incident reading "1 failed assertion: a321883ce7"
        tells the on-call nothing about what broke.
        """
        from agent.tools.warehouse.dbt_runner import _readable

        info = self.graph.get_aspect(assertion_urn, AssertionInfoClass)
        if info and info.customProperties:
            uid = info.customProperties.get("dbt_unique_id")
            if uid:  # e.g. test.fraud_pipeline.assert_avg_txn_amount_plausible
                return _readable(uid)
        if info and info.description:
            return info.description
        return _short_name(assertion_urn)

    def _failed_assertions(self, dataset_urn: str) -> list[str]:
        q = """
        query($urn:String!){
          dataset(urn:$urn){
            assertions(start:0,count:50){
              assertions{
                urn
                runEvents(status:COMPLETE, limit:1){ runEvents { result { type } } }
              }
            }
          }
        }"""
        res = self.graph.execute_graphql(q, variables={"urn": dataset_urn})
        ds = res.get("dataset") or {}
        blocks = (ds.get("assertions") or {}).get("assertions") or []
        failed = []
        for a in blocks:
            events = (a.get("runEvents") or {}).get("runEvents") or []
            if events and events[0]["result"]["type"] == "FAILURE":
                failed.append(self._assertion_name(a["urn"]))
        return failed

    def detect_incidents(self) -> list[Incident]:
        incidents: list[Incident] = []
        dbt_datasets = self.graph.get_urns_by_filter(
            entity_types=["dataset"], platform="dbt"
        )
        for urn in dbt_datasets:
            failed = self._failed_assertions(urn)
            if failed:
                incidents.append(
                    Incident(
                        id=f"INC-{abs(hash(urn)) % 10000:04d}",
                        asset_urn=urn,
                        signal_type=SignalType.ASSERTION_FAILURE,
                        detected_at=datetime.now(timezone.utc),
                        summary=f"{len(failed)} failed assertion(s) on "
                        f"{_short_name(urn)}: {', '.join(failed)}",
                        raw_evidence={"failed_assertions": failed},
                    )
                )
        return incidents

    # ------------------------------------------------------------------ #
    # context
    # ------------------------------------------------------------------ #
    def _lineage(self, urn: str, direction: str) -> list[LineageNode]:
        q = """
        query($urn:String!,$dir:LineageDirection!){
          searchAcrossLineage(input:{urn:$urn, direction:$dir, query:"*",
                                     start:0, count:100}){
            searchResults { entity { urn type } }
          }
        }"""
        res = self.graph.execute_graphql(q, variables={"urn": urn, "dir": direction})
        results = (res.get("searchAcrossLineage") or {}).get("searchResults") or []
        self_name = _short_name(urn)
        nodes: list[LineageNode] = []
        seen: set[str] = set()
        for r in results:
            e = r["entity"]
            name = _short_name(e["urn"])
            # dedupe dbt/duckdb siblings by name, and drop self-references
            if name == self_name or name in seen:
                continue
            seen.add(name)
            nodes.append(
                LineageNode(
                    urn=e["urn"],
                    name=name,
                    entity_type=_GQL_TYPE_TO_ENTITY.get(e["type"], e["type"].lower()),
                )
            )
        return nodes

    def read_context(self, asset_urn: str) -> ContextBundle:
        schema = self.graph.get_aspect(asset_urn, SchemaMetadataClass)
        fields = [f.fieldPath for f in schema.fields] if schema else []

        tags_aspect = self.graph.get_aspect(asset_urn, GlobalTagsClass)
        tags = [t.tag.split(":")[-1] for t in tags_aspect.tags] if tags_aspect else []

        own = self.graph.get_aspect(asset_urn, OwnershipClass)
        owners = [o.owner.split(":")[-1] for o in own.owners] if own else []

        return ContextBundle(
            asset_urn=asset_urn,
            name=_short_name(asset_urn),
            entity_type="dataset",
            upstream=self._lineage(asset_urn, "UPSTREAM"),
            downstream=self._lineage(asset_urn, "DOWNSTREAM"),
            schema_fields=fields,
            owners=owners,
            tags=tags,
            failed_assertions=self._failed_assertions(asset_urn),
        )
