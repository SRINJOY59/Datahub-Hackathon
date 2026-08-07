"""Closing an incident in the graph.

Three things have to happen when an incident resolves, and all three are about
the *next* person rather than this run:

  1. the post-mortem is recorded where it will be found again — on the failing
     asset, and on the ML model downstream of it, because the model card is where
     someone debugging a bad prediction actually looks;
  2. the "do not trust" tags come off, so the warning never outlives the problem
     it was warning about;
  3. the asset is stamped resolved, so the graph shows the incident happened and
     was handled rather than showing nothing at all.

Recording goes through the injected MemoryStore rather than being written here
directly, so there is one path into memory and no chance of a post-mortem being
stored twice in slightly different shapes.
"""
from __future__ import annotations

import datahub.emitter.mce_builder as builder
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    GlobalTagsClass,
    TagAssociationClass,
    TagPropertiesClass,
)

from agent.contracts import ContextBundle, MemoryStore, PostMortem
from agent.tools.actuators.tag_asset import DEGRADED_TAG
from agent.tools.graph.urns import is_model

RESOLVED_TAG = "Sentinel-Resolved"
RESOLVED_DESC = ("Sentinel detected, root-caused and resolved an incident on this "
                 "asset. See the linked post-mortem in Documentation.")


class DataHubWriteBack:
    def __init__(self, gms_server: str = "http://localhost:8080",
                 memory: MemoryStore | None = None) -> None:
        self.gms_server = gms_server
        self.graph = DataHubGraph(DataHubGraphConfig(server=gms_server))
        self.memory = memory

    # ------------------------------------------------------------------ #
    def write_back(self, pm: PostMortem,
                   context: ContextBundle | None = None,
                   resolved: bool = True) -> None:
        """Record the outcome in the graph.

        `resolved=False` means the agent contained the incident but could not
        repair it — a stale feed, say, where the missing rows are simply not
        something an agent can conjure. The post-mortem is still written, because
        memory should learn from the incidents we cannot fix as much as the ones
        we can, but the warnings stay up: the downstream assets keep
        `Sentinel-Degraded`, and nothing is stamped resolved. Clearing them here
        would tell every reader of the catalog that the data is fine when it
        demonstrably is not.
        """
        self._record(pm)
        self._record_on_models(pm, context)
        if resolved:
            self._clear_degraded(pm, context)
            self._stamp_resolved(pm.asset_urn)

    # ------------------------------------------------------------------ #
    def _record(self, pm: PostMortem) -> None:
        if self.memory:
            self.memory.record(pm)

    def _record_on_models(self, pm: PostMortem,
                          context: ContextBundle | None) -> None:
        """Also attach the post-mortem to downstream models. An incident in a
        feature table is the model owner's problem too, and they will never think
        to look at the feature table's page."""
        if not (self.memory and context):
            return
        for node in context.downstream:
            if not is_model(node.urn):
                continue
            self.memory.record(PostMortem(
                incident_id=pm.incident_id,
                asset_urn=node.urn,
                root_cause=pm.root_cause,
                blast_radius=pm.blast_radius,
                actions_taken=pm.actions_taken,
                resolution=pm.resolution,
                resolved_at=pm.resolved_at,
            ))

    def _clear_degraded(self, pm: PostMortem,
                        context: ContextBundle | None) -> None:
        """Take the quarantine warning off everything it was applied to."""
        targets = {pm.asset_urn, *pm.blast_radius}
        if context:
            targets.update(n.urn for n in context.downstream)
        for urn in targets:
            try:
                self._remove_tag(urn, DEGRADED_TAG)
            except Exception:
                continue  # one unreachable asset must not block the rest

    def _stamp_resolved(self, urn: str) -> None:
        try:
            self._define_tag(RESOLVED_TAG, RESOLVED_DESC)
            self._add_tag(urn, RESOLVED_TAG)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def _tags(self, urn: str) -> GlobalTagsClass:
        return self.graph.get_aspect(urn, GlobalTagsClass) or GlobalTagsClass(tags=[])

    def _add_tag(self, urn: str, tag: str) -> None:
        tag_urn = builder.make_tag_urn(tag)
        existing = self._tags(urn)
        if any(t.tag == tag_urn for t in existing.tags):
            return
        existing.tags.append(TagAssociationClass(tag=tag_urn))
        self.graph.emit_mcp(MetadataChangeProposalWrapper(
            entityUrn=urn, aspect=existing))

    def _remove_tag(self, urn: str, tag: str) -> None:
        tag_urn = builder.make_tag_urn(tag)
        existing = self._tags(urn)
        remaining = [t for t in existing.tags if t.tag != tag_urn]
        if len(remaining) == len(existing.tags):
            return
        self.graph.emit_mcp(MetadataChangeProposalWrapper(
            entityUrn=urn, aspect=GlobalTagsClass(tags=remaining)))

    def _define_tag(self, tag: str, description: str) -> None:
        self.graph.emit_mcp(MetadataChangeProposalWrapper(
            entityUrn=builder.make_tag_urn(tag),
            aspect=TagPropertiesClass(name=tag, description=description),
        ))
