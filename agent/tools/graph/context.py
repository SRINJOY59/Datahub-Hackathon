"""DataHub-backed context tool — the real read side of the mechanism interface.

Reads lineage, schema, ownership, tags, and failing assertions from the graph,
and surfaces open incidents (datasets whose latest assertion run FAILED). This is
what gives the agent real understanding instead of guesses.
"""
from __future__ import annotations

import os
import time
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


_URN_PREFIX_TO_ENTITY = {
    "urn:li:dataset:": "dataset",
    "urn:li:mlModelDeployment:": "mlModelDeployment",
    "urn:li:mlModelGroup:": "mlModelGroup",
    "urn:li:mlModel:": "mlModel",
    "urn:li:dataJob:": "dataJob",
    "urn:li:dataFlow:": "dataFlow",
}


def _entity_type_from_urn(urn: str) -> str:
    """The MCP lineage tool returns urns without a separate type field, so derive
    it from the urn — which is unambiguous."""
    for prefix, kind in _URN_PREFIX_TO_ENTITY.items():
        if urn.startswith(prefix):
            return kind
    return "dataset"


"""Lineage breaker — a degraded GMS must not stall the whole loop.

DataHub's shallow /health can pass while `searchAcrossLineage` (which goes to
Elasticsearch) hangs. Without this, every incident the agent handles pays the
full client timeout and then dies on the exception, so a slow graph looks
exactly like a broken agent. Instead: fail fast, degrade to empty lineage, and
stop asking for a cooldown once the graph has proved unwell.
"""
_LINEAGE_TIMEOUT_SEC = float(os.environ.get("DATAHUB_LINEAGE_TIMEOUT_SEC", "8"))
_BREAKER_THRESHOLD = 3      # consecutive failures before we stop asking
_BREAKER_COOLDOWN_SEC = 120

_lineage_failures = 0
_lineage_breaker_until = 0.0


def _lineage_breaker_open() -> bool:
    return time.monotonic() < _lineage_breaker_until


def _note_lineage_failure() -> None:
    global _lineage_failures, _lineage_breaker_until
    _lineage_failures += 1
    if _lineage_failures >= _BREAKER_THRESHOLD:
        _lineage_breaker_until = time.monotonic() + _BREAKER_COOLDOWN_SEC
        _lineage_failures = 0
        print(f"[context] DataHub lineage unresponsive — skipping lineage "
              f"for {_BREAKER_COOLDOWN_SEC}s; RCA continues without graph context")


def _note_lineage_success() -> None:
    global _lineage_failures
    _lineage_failures = 0


class DataHubContextTool:
    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.graph = DataHubGraph(DataHubGraphConfig(
            server=gms_server, timeout_sec=_LINEAGE_TIMEOUT_SEC))

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
        """Lineage via the DataHub MCP Server when enabled, else the SDK.

        Lineage is enriching context, not a precondition for reasoning: when the
        graph cannot answer, the agent is better off diagnosing from assertions
        and schema than failing the incident outright.
        """
        if _lineage_breaker_open():
            return []
        try:
            nodes = self._lineage_mcp(urn, direction)
            if nodes is None:
                nodes = self._lineage_sdk(urn, direction)
        except Exception as exc:
            _note_lineage_failure()
            print(f"[context] lineage lookup failed for {_short_name(urn)} "
                  f"({direction}): {type(exc).__name__}")
            return []
        _note_lineage_success()
        return nodes

    def _lineage_mcp(self, urn: str, direction: str) -> list[LineageNode] | None:
        from agent.tools.mcp.client import shared_mcp

        mcp = shared_mcp()
        if mcp is None:
            return None
        upstream = direction == "UPSTREAM"
        res = mcp.call_json("get_lineage", {"urn": urn, "upstream": upstream,
                                            "max_hops": 3, "max_results": 100})
        block = res.get("upstreams" if upstream else "downstreams") or {}
        results = block.get("searchResults")
        if not results:
            return None  # empty or failed -> let the SDK have a go
        return self._dedupe([r.get("entity", {}).get("urn") for r in results], urn)

    def _lineage_sdk(self, urn: str, direction: str) -> list[LineageNode]:
        q = """
        query($urn:String!,$dir:LineageDirection!){
          searchAcrossLineage(input:{urn:$urn, direction:$dir, query:"*",
                                     start:0, count:100}){
            searchResults { entity { urn } }
          }
        }"""
        res = self.graph.execute_graphql(q, variables={"urn": urn, "dir": direction})
        results = (res.get("searchAcrossLineage") or {}).get("searchResults") or []
        return self._dedupe([r["entity"]["urn"] for r in results], urn)

    @staticmethod
    def _dedupe(urns: list[str], self_urn: str) -> list[LineageNode]:
        """Collapse dbt/duckdb siblings by name and drop self-references, so the
        agent reasons over one logical node per table regardless of source."""
        self_name = _short_name(self_urn)
        nodes: list[LineageNode] = []
        seen: set[str] = set()
        for eurn in urns:
            if not eurn:
                continue
            name = _short_name(eurn)
            if name == self_name or name in seen:
                continue
            seen.add(name)
            nodes.append(LineageNode(urn=eurn, name=name,
                                     entity_type=_entity_type_from_urn(eurn)))
        return nodes

    def _schema_fields(self, urn: str) -> list[str]:
        """Schema via the DataHub MCP Server when enabled, else the SDK."""
        from agent.tools.mcp.client import shared_mcp

        mcp = shared_mcp()
        if mcp is not None:
            res = mcp.call_json("list_schema_fields", {"urn": urn})
            fields = res.get("fields")
            if fields:
                return [f["fieldPath"] for f in fields if f.get("fieldPath")]
        schema = self.graph.get_aspect(urn, SchemaMetadataClass)
        return [f.fieldPath for f in schema.fields] if schema else []

    def read_context(self, asset_urn: str) -> ContextBundle:
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
            schema_fields=self._schema_fields(asset_urn),
            owners=owners,
            tags=tags,
            failed_assertions=self._failed_assertions(asset_urn),
        )
