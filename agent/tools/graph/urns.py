"""Reading DataHub URNs.

Several layers need the same few facts about a urn — is this a dataset or a
model, which warehouse table does it refer to — and each was picking the string
apart on its own. Parsing in one place keeps them from disagreeing about what an
incident is actually pointing at.

A dataset urn looks like:
    urn:li:dataset:(urn:li:dataPlatform:dbt,fraud_demo.fraud.main.amounts,PROD)
where the second comma-separated token is the dotted dataset name and its last
segment is the physical table.
"""
from __future__ import annotations

import datahub.emitter.mce_builder as builder

ENV = "PROD"

DATASET_PREFIX = "urn:li:dataset:"
MODEL_PREFIXES = ("urn:li:mlModel:", "urn:li:mlModelDeployment:",
                  "urn:li:mlModelGroup:")


def is_dataset(urn: str) -> bool:
    return (urn or "").startswith(DATASET_PREFIX)


def is_model(urn: str) -> bool:
    return (urn or "").startswith(MODEL_PREFIXES)


def dataset_name(urn: str) -> str:
    """The dotted name, e.g. 'fraud_demo.fraud.main.feat_user_txn_stats'."""
    try:
        return urn.split(",")[1]
    except (AttributeError, IndexError):
        return ""


def table_of(urn: str) -> str:
    """The physical table an asset urn refers to, or '' if it isn't a dataset."""
    if not is_dataset(urn):
        return ""
    return dataset_name(urn).split(".")[-1]


def name_prefix(urn: str) -> str:
    """The schema portion of a dataset name — what sibling tables share."""
    name = dataset_name(urn)
    return name.rsplit(".", 1)[0] if "." in name else name


def short_name(urn: str) -> str:
    """A human-readable label for any entity type."""
    if is_dataset(urn):
        return table_of(urn)
    if is_model(urn):
        return dataset_name(urn)
    if (urn or "").startswith("urn:li:dataJob:"):
        return urn.split(",")[-1].rstrip(")")
    return urn or ""


def sibling_dataset_urn(reference_urn: str, table: str) -> str:
    """The dbt urn for another table in the same schema as `reference_urn`.

    Used when a probe blames an upstream table and we need its urn without
    another round-trip to the graph.
    """
    prefix = name_prefix(reference_urn)
    return builder.make_dataset_urn("dbt", f"{prefix}.{table}", ENV)
