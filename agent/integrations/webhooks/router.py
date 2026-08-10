"""EventRouter — parse webhook payloads and map them to agent run requests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agent.integrations.webhooks.config import WebhookConfig


@dataclass
class AgentRunRequest:
    asset_urn: str
    source: str
    signal_hint: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class EventRouter:
    def __init__(self, config: WebhookConfig) -> None:
        self.config = config

    def route(self, source: str, payload: dict) -> Optional[AgentRunRequest]:
        src_cfg = self.config.sources.get(source)
        if not src_cfg or not src_cfg.enabled:
            return None

        handler = getattr(self, f"_parse_{source}", None)
        if handler:
            return handler(payload, src_cfg)
        return None

    def _parse_dbt(self, payload: dict, src) -> Optional[AgentRunRequest]:
        data = payload.get("data", payload)
        job_name = data.get("jobName") or data.get("job_name", "")
        run_status = data.get("runStatus") or data.get("status", "")

        asset_urn = src.job_to_asset.get(job_name)
        if not asset_urn:
            return None

        return AgentRunRequest(
            asset_urn=asset_urn,
            source="dbt",
            signal_hint="assertion_failure" if "error" in run_status.lower() else None,
            metadata={
                "job_name": job_name,
                "run_id": data.get("runId") or data.get("run_id"),
                "status": run_status,
            },
        )

    def _parse_airflow(self, payload: dict, src) -> Optional[AgentRunRequest]:
        dag_id = payload.get("dag_id", "")
        task_id = payload.get("task_id", "")
        execution_date = payload.get("execution_date", "")

        asset_urn = src.dag_to_asset.get(dag_id)
        if not asset_urn:
            return None

        return AgentRunRequest(
            asset_urn=asset_urn,
            source="airflow",
            signal_hint="assertion_failure",
            metadata={
                "dag_id": dag_id,
                "task_id": task_id,
                "execution_date": execution_date,
            },
        )

    def _parse_github(self, payload: dict, _src) -> Optional[AgentRunRequest]:
        # Case 1: GitHub Release Webhook (action="published", "created", etc.)
        if "release" in payload:
            rel = payload.get("release", {})
            repo = payload.get("repository", {}).get("name", "")
            tag = rel.get("tag_name", "")
            body = rel.get("body", "")

            return AgentRunRequest(
                asset_urn="__github_release__",
                source="github_release",
                signal_hint="dependency_change",
                metadata={
                    "package": repo,
                    "tag_name": tag,
                    "release_name": rel.get("name", tag),
                    "body": body,
                    "published_at": rel.get("published_at", ""),
                },
            )

        # Case 2: GitHub Push Webhook
        commits = payload.get("commits", [])
        if not commits:
            return None

        changed_files: list[str] = []
        for commit in commits:
            changed_files.extend(commit.get("added", []))
            changed_files.extend(commit.get("modified", []))

        if not changed_files:
            return None

        return AgentRunRequest(
            asset_urn="__git_push__",
            source="github",
            signal_hint="code_change",
            metadata={
                "ref": payload.get("ref", ""),
                "head_sha": payload.get("after", ""),
                "changed_files": changed_files,
                "pusher": payload.get("pusher", {}).get("name", ""),
            },
        )

    def _parse_advisory(self, payload: dict, _src) -> Optional[AgentRunRequest]:
        package = payload.get("package", "")
        if not package:
            return None

        # Resolve impacted asset via codebase memory if available
        asset_urn = "__advisory__"
        try:
            from memory.codebase import shared_codebase
            cb = shared_codebase()
            impacted = cb.impacted_assets(package)
            if impacted:
                asset_urn = impacted[0]
        except Exception:
            pass

        return AgentRunRequest(
            asset_urn=asset_urn,
            source="advisory",
            signal_hint="dependency_change",
            metadata={
                "package": package,
                "from_version": payload.get("from_version", ""),
                "to_version": payload.get("to_version", ""),
                "summary": payload.get("summary", ""),
                "migration": payload.get("migration", ""),
                "symbols": payload.get("symbols", []),
            },
        )


    def _parse_generic(self, payload: dict, _src) -> Optional[AgentRunRequest]:
        asset_urn = payload.get("asset_urn")
        if not asset_urn:
            return None

        return AgentRunRequest(
            asset_urn=asset_urn,
            source="generic",
            signal_hint=payload.get("signal_type"),
            metadata=payload.get("metadata", {}),
        )

