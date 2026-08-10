"""Load webhook config from config/webhooks.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_CONFIG_PATH = Path("config/webhooks.yaml")


@dataclass
class SourceConfig:
    enabled: bool = False
    job_to_asset: dict[str, str] = field(default_factory=dict)
    dag_to_asset: dict[str, str] = field(default_factory=dict)


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8090
    workers: int = 2


@dataclass
class WebhookConfig:
    enabled: bool = False
    server: ServerConfig = field(default_factory=ServerConfig)
    sources: dict[str, SourceConfig] = field(default_factory=dict)
    sweep_interval_minutes: int = 0
    auto_remediate: bool = True

    @classmethod
    def load(cls) -> WebhookConfig:
        if not _CONFIG_PATH.exists():
            return cls()
        try:
            raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            return cls()

        srv = raw.get("server", {})
        server = ServerConfig(
            host=srv.get("host", "0.0.0.0"),
            port=srv.get("port", 8090),
            workers=srv.get("workers", 2),
        )

        sources: dict[str, SourceConfig] = {}
        for name, src in (raw.get("sources") or {}).items():
            if not isinstance(src, dict):
                src = {}
            sources[name] = SourceConfig(
                enabled=src.get("enabled", False),
                job_to_asset=src.get("job_to_asset") or {},
                dag_to_asset=src.get("dag_to_asset") or {},
            )

        schedule = raw.get("schedule", {})
        sweep = schedule.get("sweep_interval_minutes", 0) if isinstance(schedule, dict) else 0
        auto_remediate = schedule.get("auto_remediate", True) if isinstance(schedule, dict) else True

        return cls(
            enabled=raw.get("enabled", False),
            server=server,
            sources=sources,
            sweep_interval_minutes=sweep,
            auto_remediate=auto_remediate,
        )


    def secret_for(self, source: str) -> str | None:
        return os.environ.get(f"WEBHOOK_SECRET_{source.upper()}")
