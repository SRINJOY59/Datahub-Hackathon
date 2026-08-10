"""Apply ownership + governance tags to the fraud assets in DataHub.

These are the agent's POLICY INPUTS:

  * Tier-Critical -> code fixes must go through a PR (no silent auto-apply)
  * PII           -> incidents always page a human owner

Ownership drives the audience-aware incident comms. Idempotent.
"""
import os
from typing import Optional

import datahub.emitter.mce_builder as builder
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    CorpUserInfoClass,
    GlobalTagsClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    TagAssociationClass,
    TagPropertiesClass,
)

ENV = "PROD"

DATA_ENG = builder.make_user_urn("jordan.rivera")
ML_ENG = builder.make_user_urn("sam.chen")

USERS = {
    DATA_ENG: ("Jordan Rivera", "jordan.rivera@sentinel.demo", "Data Engineer"),
    ML_ENG: ("Sam Chen", "sam.chen@sentinel.demo", "ML Engineer"),
}

TAGS = {
    "Tier-Critical": "Business-critical asset. Autonomous code fixes require a "
    "human-approved PR (no silent auto-apply).",
    "PII": "Contains personally identifiable / sensitive financial data. "
    "Incidents on this asset always page a human owner.",
}

# name -> (tags, owner)
DATASETS = {
    "raw_transactions": (["PII"], DATA_ENG),
    "stg_transactions": (["PII"], DATA_ENG),
    "feat_user_txn_stats": (["Tier-Critical", "PII"], DATA_ENG),
    "feat_merchant_risk": ([], DATA_ENG),
    "training_dataset": (["Tier-Critical"], ML_ENG),
}


class GovernanceApplier:
    """Emits tag definitions, owners, and per-asset tag/owner associations."""

    def __init__(self, gms_server: Optional[str] = None) -> None:
        server = gms_server or os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
        self.graph = DataHubGraph(DataHubGraphConfig(server=server))
        self.model_urn = builder.make_ml_model_urn("mlflow", "fraud_detection_model_1", ENV)
        self.deploy_urn = builder.make_ml_model_deployment_urn("mlflow", "fraud_scoring_api", ENV)

    @staticmethod
    def _dataset_urns(name: str) -> list[str]:
        return [
            builder.make_dataset_urn("dbt", f"fraud_demo.fraud.main.{name}", ENV),
            builder.make_dataset_urn("duckdb", f"fraud.main.{name}", ENV),
        ]

    @staticmethod
    def _tags(names: list[str]) -> GlobalTagsClass:
        return GlobalTagsClass(
            tags=[TagAssociationClass(tag=builder.make_tag_urn(n)) for n in names]
        )

    @staticmethod
    def _owner(owner: str) -> OwnershipClass:
        return OwnershipClass(
            owners=[OwnerClass(owner=owner, type=OwnershipTypeClass.TECHNICAL_OWNER)]
        )

    def apply(self) -> None:
        mcps: list[MetadataChangeProposalWrapper] = []

        for name, desc in TAGS.items():
            mcps.append(MetadataChangeProposalWrapper(
                entityUrn=builder.make_tag_urn(name),
                aspect=TagPropertiesClass(name=name, description=desc)))

        for urn, (display, email, title) in USERS.items():
            mcps.append(MetadataChangeProposalWrapper(
                entityUrn=urn,
                aspect=CorpUserInfoClass(active=True, displayName=display, email=email, title=title)))

        for name, (tags, owner) in DATASETS.items():
            for urn in self._dataset_urns(name):
                if tags:
                    mcps.append(MetadataChangeProposalWrapper(entityUrn=urn, aspect=self._tags(tags)))
                mcps.append(MetadataChangeProposalWrapper(entityUrn=urn, aspect=self._owner(owner)))

        for urn in (self.model_urn, self.deploy_urn):
            mcps.append(MetadataChangeProposalWrapper(entityUrn=urn, aspect=self._tags(["Tier-Critical"])))
            mcps.append(MetadataChangeProposalWrapper(entityUrn=urn, aspect=self._owner(ML_ENG)))

        for mcp in mcps:
            self.graph.emit_mcp(mcp)

        print(f"  applied: {len(TAGS)} tags, {len(USERS)} owners, "
              f"{len(DATASETS)} datasets + model + deployment")


if __name__ == "__main__":
    GovernanceApplier().apply()
