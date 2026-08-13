"""Actuator: mark downstream assets as not to be trusted — the circuit breaker.

This is the mitigation that protects people rather than data. Long before the
underlying fix lands, everyone who opens one of these assets in DataHub can see
that the agent believes it is currently unreliable, and why. The tag is removed
automatically when the incident resolves, so the warning never outlives the
problem.

Tags are read-modify-written rather than overwritten, because an asset's existing
governance tags (PII, Tier-Critical) are what decide how the agent is allowed to
behave — clobbering them would quietly widen its own autonomy.
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

from agent.contracts import ActionRecord, ActionType
from agent.registry import actuator
from agent.tools.actuators.base import BaseActuator

DEGRADED_TAG = "Sentinel-Degraded"
DEGRADED_DESC = ("Sentinel has an open incident affecting this asset. Its data "
                 "may be unreliable until the incident is resolved; the tag is "
                 "removed automatically on resolution.")


@actuator
class TagAssetActuator(BaseActuator):
    name = "tag_asset"
    action_type = ActionType.TAG_ASSET

    def __init__(self, gms_server: str | None = None) -> None:
        from agent.gms import default_gms_server

        gms_server = gms_server or default_gms_server()
        self.graph = DataHubGraph(DataHubGraphConfig(server=gms_server))

    # ------------------------------------------------------------------ #
    def _apply(self, action: ActionRecord) -> ActionRecord:
        tag = action.params.get("tag", DEGRADED_TAG)
        self._define_tag(tag)
        added = self._set_tag(action.target, tag, present=True)

        action.note = (action.note + (f" | tagged {tag}" if added
                                      else f" | {tag} already present")).strip(" |")
        return ActionRecord(
            action_type=self.action_type,
            target=action.target,
            params={"tag": tag, "remove": True, "was_present": not added},
            note=f"remove {tag}",
            incident_id=action.incident_id,
        )

    def _revert(self, inverse: ActionRecord) -> bool:
        # If the tag was already there before we acted, leaving it is the correct
        # restoration — we did not put it there.
        if inverse.params.get("was_present"):
            return True
        self._set_tag(inverse.target, inverse.params.get("tag", DEGRADED_TAG),
                      present=False)
        return True

    # ------------------------------------------------------------------ #
    def _define_tag(self, tag: str) -> None:
        """Give the tag a description so it reads as intentional in the UI."""
        try:
            self.graph.emit_mcp(MetadataChangeProposalWrapper(
                entityUrn=builder.make_tag_urn(tag),
                aspect=TagPropertiesClass(name=tag, description=DEGRADED_DESC),
            ))
        except Exception:
            pass  # a missing description must not block the mitigation

    def _set_tag(self, urn: str, tag: str, present: bool) -> bool:
        """Add or remove one tag, preserving the others. Returns whether the
        asset's tags actually changed."""
        tag_urn = builder.make_tag_urn(tag)
        existing = self.graph.get_aspect(urn, GlobalTagsClass) or GlobalTagsClass(tags=[])
        current = [t for t in existing.tags if t.tag != tag_urn]
        had_it = len(current) != len(existing.tags)

        if present and had_it:
            return False
        if not present and not had_it:
            return False

        if present:
            current.append(TagAssociationClass(tag=tag_urn))
        self.graph.emit_mcp(MetadataChangeProposalWrapper(
            entityUrn=urn, aspect=GlobalTagsClass(tags=current)))
        return True
