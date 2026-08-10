"""Convert incidents into Slack Block Kit messages."""
from __future__ import annotations

from typing import Optional

from agent.contracts import (
    ActionRecord,
    ContextBundle,
    CostEstimate,
    Incident,
    IncidentOutcome,
    RootCauseAnalysis,
)
from agent.reporting.comms import _PLAIN
from agent.tools.graph.urns import short_name

_SEVERITY_EMOJI = {
    "high": ":red_circle:",
    "medium": ":large_orange_circle:",
    "low": ":large_yellow_circle:",
}

_STATUS_EMOJI = {
    "resolved": ":white_check_mark:",
    "contained": ":warning:",
    "rolled_back": ":rewind:",
    "escalated": ":rotating_light:",
    "shadow": ":ghost:",
    "code_fix": ":wrench:",
    "correlated": ":link:",
}


def _get_repo_name(context: Optional[ContextBundle] = None, asset_urn: str = "") -> str:
    try:
        import json
        from api.shared import get_active_repo_id
        from api.repo_onboarding import ConnectedRepoStore

        target_urn = ""
        if context:
            target_urn = getattr(context, "asset_urn", getattr(context, "urn", ""))
        if not target_urn:
            target_urn = asset_urn
        if not target_urn:
            return get_active_repo_id()

        store = ConnectedRepoStore()
        for repo in store.list():
            lineage = json.loads(repo.get("lineage_json") or "{}")
            urns = {d.get("urn") for d in lineage.get("datasets", [])}
            urns.update(m.get("urn") for m in lineage.get("models", []))
            urns.update(j.get("urn") for j in lineage.get("jobs", []))
            if target_urn in urns:
                return repo.get("repo_name", "")
        return get_active_repo_id()
    except Exception:
        return "default"


def detect_engineer(
    incident: Incident,
    context: ContextBundle,
    rca: RootCauseAnalysis,
    cost: CostEstimate,
) -> tuple[list[dict], str]:
    """Block Kit blocks + fallback text for the engineer channel."""
    emoji = _SEVERITY_EMOJI.get(rca.confidence, ":large_orange_circle:")
    asset = context.name
    repo_name = _get_repo_name(context)
    root = short_name(rca.root_cause_asset)
    if rca.root_cause_column:
        root += f".{rca.root_cause_column}"
    owners = ", ".join(context.owners) or "unassigned"

    blocks = [
        _header(f"{emoji} [{rca.change_type.value}] {asset} ({repo_name})"),
        _section(f"*Repository:* `{repo_name}`\n*Root cause:* `{root}`\n{rca.narrative}"),
    ]

    fields = [
        f"*Repository:* `{repo_name}`",
        f"*Confidence:* {rca.confidence}",
        f"*Exposure:* ${cost.dollars:,.0f}" if cost.dollars else "*Exposure:* n/a",
    ]
    commit = (incident.raw_evidence or {}).get("commit")
    if commit:
        fields.append(f"*Commit:* `{commit.get('sha', '?')[:8]}` by {commit.get('author', '?')}")
    blocks.append(_fields(fields))

    if rca.upstream_path:
        blocks.append(_section("*Lineage:* " + " :arrow_left: ".join(rca.upstream_path)))

    blocks.append(_section(f"*First action:* {rca.recommended_mitigation}"))
    blocks.append(_context(f"Repo: {repo_name} | Owners: {owners} | Incident: {incident.id}"))

    fallback = f"[{rca.change_type.value}] {asset} ({repo_name}) — root cause: {root}"
    return blocks, fallback


def detect_analyst(
    context: ContextBundle,
    rca: RootCauseAnalysis,
) -> tuple[list[dict], str]:
    plain = _PLAIN.get(rca.change_type.value, _PLAIN["unknown"])
    asset = context.name
    repo_name = _get_repo_name(context)
    downstream = [n.name for n in context.downstream]
    blast = ", ".join(downstream) if downstream else "no downstream consumers"
    owners = ", ".join(context.owners) or "unassigned"

    blocks = [
        _header(f":warning: Data quality alert — {asset} ({repo_name})"),
        _section(
            f"*Repository:* `{repo_name}`\n"
            f"*What happened:* {plain}, in *{asset}*.\n"
            f"*Affected downstream:* {blast}."
        ),
        _section(
            f":no_entry: Please do not rely on these until an engineer "
            f"clears it ({owners})."
        ),
        _context(f"Repository: {repo_name}"),
    ]
    fallback = f"Data alert [{repo_name}]: {plain} in {asset}. Downstream: {blast}."
    return blocks, fallback


def detect_executive(
    context: ContextBundle,
    rca: RootCauseAnalysis,
    cost: CostEstimate,
) -> tuple[list[dict], str]:
    asset = context.name
    repo_name = _get_repo_name(context)
    plain = _PLAIN.get(rca.change_type.value, _PLAIN["unknown"])
    dollars = f"${cost.dollars:,.0f}" if cost.dollars else "not estimated"
    owners = ", ".join(context.owners) or "unassigned"

    text = (
        f"*[{repo_name}] {asset}:* {plain}. Estimated business exposure at risk: "
        f"*{dollars}*. Status: detected. Owner: {owners}."
    )
    blocks = [_section(text), _context(f"Repository: {repo_name}")]
    return blocks, text


def status_update(
    outcome: IncidentOutcome,
    extra: str = "",
) -> tuple[list[dict], str]:
    emoji = _STATUS_EMOJI.get(outcome.status, ":information_source:")
    status_upper = outcome.status.replace("_", " ").upper()
    actions = ", ".join(outcome.actions_taken) if outcome.actions_taken else "none"

    text = f"{emoji} *{status_upper}* — actions: {actions}"
    if outcome.pr:
        text += f"\nFix PR: {outcome.pr}"
    if extra:
        text += f"\n{extra}"

    blocks = [_section(text)]
    return blocks, text


def approval_request(
    incident: Incident,
    actions: list[ActionRecord],
    context: ContextBundle,
    rca: RootCauseAnalysis,
) -> tuple[list[dict], str]:
    asset = context.name
    action_list = "\n".join(
        f"• *{a.action_type.value}* on `{short_name(a.target)}`"
        for a in actions
    )

    blocks = [
        _header(f":lock: Approval required — {asset}"),
        _section(
            f"*{rca.change_type.value}* detected (confidence: {rca.confidence}).\n"
            f"The agent wants to:\n{action_list}"
        ),
        {
            "type": "actions",
            "block_id": f"approval_{incident.id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "sentinel_approve",
                    "value": incident.id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deny"},
                    "style": "danger",
                    "action_id": "sentinel_deny",
                    "value": incident.id,
                },
            ],
        },
        _context(f"Timeout: approval config applies | Incident: {incident.id}"),
    ]
    fallback = f"Approval required for {asset}: {', '.join(a.action_type.value for a in actions)}"
    return blocks, fallback


def resolve_analyst(
    context: ContextBundle,
    resolved: bool,
) -> tuple[list[dict], str]:
    asset = context.name
    if resolved:
        text = f":white_check_mark: *{asset}* is fixed — the data is safe to use again."
    else:
        text = f":warning: *{asset}* is contained but not yet resolved. Still avoid relying on this data."
    return [_section(text)], text


def resolve_executive(
    context: ContextBundle,
    cost: CostEstimate,
    resolved: bool,
) -> tuple[list[dict], str]:
    asset = context.name
    dollars = f"${cost.dollars:,.0f}" if cost.dollars else "n/a"
    if resolved:
        text = f":white_check_mark: *{asset}* resolved. Exposure avoided: *{dollars}*."
    else:
        text = f":warning: *{asset}* contained, awaiting human. Exposure at risk: *{dollars}*."
    return [_section(text)], text


def repo_onboarded(result: Any) -> tuple[list[dict], str]:
    """Block Kit blocks for repository onboarding notification across any connected repo."""
    name = getattr(result, "repo_name", "Repository")
    datasets = getattr(result, "datasets_count", 0)
    models = getattr(result, "models_count", 0)
    jobs = getattr(result, "jobs_count", 0)
    edges = getattr(result, "lineage_edges_count", 0)
    sha = getattr(result, "commit_sha", None) or "HEAD"
    exp = getattr(result, "mlflow_experiment_name", "N/A")

    blocks = [
        _header(f":package: New Repository Connected — {name}"),
        _section(
            f"Sentinel successfully scanned, parsed AST lineage, and emitted graph nodes to DataHub for *{name}*."
        ),
        _fields([
            f"*Datasets Discovered:* {datasets}",
            f"*ML Models:* {models}",
            f"*Data Jobs:* {jobs}",
            f"*Lineage Edges:* {edges}",
            f"*Commit:* `{sha[:8]}`" if sha else "*Commit:* HEAD",
            f"*MLflow Experiment:* `{exp}`",
        ]),
        _context(f"Repository: {name} | Autonomous Sentinel DataHub Lineage Guard Active"),
    ]
    fallback = f"Repository Connected: {name} ({datasets} datasets, {models} models, {edges} lineage edges)"
    return blocks, fallback


# --- Block Kit helpers ---------------------------------------------------- #

def _header(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _fields(items: list[str]) -> dict:
    return {
        "type": "section",
        "fields": [{"type": "mrkdwn", "text": t} for t in items],
    }


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _divider() -> dict:
    return {"type": "divider"}
