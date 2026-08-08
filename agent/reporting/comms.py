"""Audience-aware incident communications.

One incident, three readers who each need something different:

  * the **engineer** who has to fix it — the root cause, the evidence, the action;
  * the **analyst** who relies on the data — what not to trust, and until when;
  * the **executive** who owns the outcome — one sentence and the dollar exposure.

The RCA narrative is already written by the loop; this tailors *around* it
deterministically, so the three messages are reliable and cost no extra model
call. The point is that the same incident reads completely differently depending
on who has to act on it — a stack trace helps no analyst, and "roc_auc" means
nothing to a VP.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from agent.contracts import ContextBundle, CostEstimate, Incident, RootCauseAnalysis
from agent.tools.graph.urns import short_name

# A lay description of each failure mode, for the non-engineer audiences.
_PLAIN = {
    "scale_shift": "values arrived at the wrong scale (e.g. cents read as dollars)",
    "null_spike": "expected values went missing",
    "range_violation": "values fell outside their plausible range",
    "schema_change": "a column the pipeline depends on was renamed or dropped",
    "distribution_drift": "the data shifted away from its normal range",
    "dependency_change": "an external library changed in a breaking way",
    "code_change": "an unreviewed code change touched this pipeline",
    "training_regression": "the model's accuracy dropped below the safe threshold",
    "model_drift": "the model's predictions drifted from their normal pattern",
    "freshness_lag": "the data feed stopped delivering new records",
    "volume_anomaly": "far fewer records arrived than usual",
    "label_leakage": "the model became artificially accurate — a sign of leakage",
    "duplicate_records": "a batch of records was delivered more than once",
    "unknown": "an anomaly was detected",
}


@dataclass
class IncidentMessages:
    engineer: str
    analyst: str
    executive: str

    def render(self) -> str:
        return ("\n--- for the on-call engineer ---\n" + self.engineer
                + "\n\n--- for data consumers / analysts ---\n" + self.analyst
                + "\n\n--- for the asset owner / exec ---\n" + self.executive)


def compose(incident: Incident, context: ContextBundle,
            rca: RootCauseAnalysis, cost: CostEstimate,
            resolved: Optional[bool] = None) -> IncidentMessages:
    """Three role-tailored write-ups of one incident.

    `resolved` is True after a successful fix, False when contained, and None
    while the incident is merely detected (announce mode) — which changes the
    status line, the guidance, and whether the exposure was *avoided* or is still
    *at risk*.
    """
    asset = context.name
    owners = ", ".join(context.owners) or "unassigned"
    plain = _PLAIN.get(rca.change_type.value, _PLAIN["unknown"])
    downstream = [n.name for n in context.downstream]
    blast = ", ".join(downstream) if downstream else "no downstream consumers"

    if resolved is True:
        status, verb = "resolved", "avoided"
    elif resolved is False:
        status, verb = "contained, awaiting review", "at risk"
    else:
        status, verb = "detected — remediation pending", "at risk"

    return IncidentMessages(
        engineer=_engineer(incident, context, rca, asset, owners, status),
        analyst=_analyst(asset, plain, blast, owners, resolved),
        executive=_executive(asset, plain, cost, verb, status, owners),
    )


def _engineer(incident, context, rca, asset, owners, status) -> str:
    root = short_name(rca.root_cause_asset)
    if rca.root_cause_column:
        root += f".{rca.root_cause_column}"
    lines = [
        f"[{rca.change_type.value}] {asset} — {status} (confidence {rca.confidence})",
        f"Root cause: {root}",
        rca.narrative,
    ]
    commit = (incident.raw_evidence or {}).get("commit")
    if commit:
        lines.append(f"Commit: {commit.get('sha')} by {commit.get('author')} "
                     f"— {commit.get('subject')}")
    if rca.upstream_path:
        lines.append("Lineage: " + " <- ".join(rca.upstream_path))
    lines.append(f"First action: {rca.recommended_mitigation}")
    lines.append(f"Owners: {owners}")
    return "\n".join(lines)


def _analyst(asset, plain, blast, owners, resolved) -> str:
    if resolved is True:
        guidance = "This is fixed — the data is safe to use again."
    else:
        guidance = (f"Please do not rely on these until an engineer clears it "
                    f"({owners}).")
    return (f"Heads-up on data you may rely on.\n"
            f"What happened: {plain}, in {asset}.\n"
            f"Affected downstream: {blast}.\n"
            f"{guidance}")


def _executive(asset, plain, cost, verb, status, owners) -> str:
    dollars = f"${cost.dollars:,.0f}" if cost.dollars else "not estimated"
    return (f"{asset}: {plain}. Estimated business exposure {verb}: {dollars}. "
            f"Status: {status}. Owner: {owners}.")
