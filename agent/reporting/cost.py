"""Estimate the business exposure an incident would have caused, left unremediated.

The honest version of a "cost meter": Sentinel does not invent a dollar figure.
It measures what is real — the actual downstream blast radius from the lineage
graph — and applies rates that live in a team-owned config file
(config/cost_model.yaml), never in this code. Every estimate cites the
assumptions it used, flags when it fell back to illustrative defaults, and yields
no dollar figure at all when the team turns the model off. A number nobody can
trace is a number nobody should trust.

    impact = sum over affected consumers( their per-hour rate )
             x assumed hours-at-risk
             x severity of this change type
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from agent.contracts import ContextBundle, CostEstimate

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "cost_model.yaml"

# Used only when config/cost_model.yaml is missing. Flagged as illustrative in
# every basis string so a fallback figure is never mistaken for a real one.
_ILLUSTRATIVE = {
    "enabled": True,
    "assumed_mttr_hours": 4,
    "per_consumer_hour": {"mlModelDeployment": 3000, "mlModel": 1500,
                          "dataset": 400, "dataJob": 200, "default": 400},
    "severity_multiplier": {"default": 1.0},
}


@dataclass
class CostModel:
    enabled: bool = True
    assumed_mttr_hours: float = 4.0
    per_consumer_hour: dict = field(default_factory=dict)
    severity_multiplier: dict = field(default_factory=dict)
    from_defaults: bool = False    # True when no config file was found

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "CostModel":
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            from_defaults = False
        except (OSError, yaml.YAMLError):
            data = _ILLUSTRATIVE
            from_defaults = True
        return cls(
            enabled=bool(data.get("enabled", True)),
            assumed_mttr_hours=float(data.get("assumed_mttr_hours", 4)),
            per_consumer_hour=data.get("per_consumer_hour", {}) or {},
            severity_multiplier=data.get("severity_multiplier", {}) or {},
            from_defaults=from_defaults,
        )

    def rate(self, kind: str) -> float:
        return float(self.per_consumer_hour.get(
            kind, self.per_consumer_hour.get("default", 0.0)))

    def severity(self, change_type: str) -> float:
        return float(self.severity_multiplier.get(
            change_type, self.severity_multiplier.get("default", 1.0)))


class CostEstimator:
    def __init__(self, model: Optional[CostModel] = None) -> None:
        self.model = model or CostModel.load()

    def estimate(self, context: ContextBundle, change_type: str) -> CostEstimate:
        # The real, measured blast radius: the asset plus everything downstream.
        counts = Counter(n.entity_type for n in context.downstream)
        counts[context.entity_type or "dataset"] += 1
        affected = sum(counts.values())
        shape = ", ".join(f"{n}x {kind}" for kind, n in counts.items())

        breakdown = {"affected_consumers": dict(counts),
                     "assumed_mttr_hours": self.model.assumed_mttr_hours}

        # Turned off: report the measured facts, assert no dollars.
        if not self.model.enabled:
            return CostEstimate(
                dollars=0.0, hours_at_risk=self.model.assumed_mttr_hours,
                breakdown=breakdown,
                basis=(f"{affected} affected consumer(s) ({shape}); "
                       f"dollar estimation disabled in config/cost_model.yaml"))

        per_hour = sum(self.model.rate(kind) * n for kind, n in counts.items())
        severity = self.model.severity(change_type)
        dollars = round(per_hour * self.model.assumed_mttr_hours * severity, 0)

        breakdown.update({"per_hour_usd": per_hour, "severity": severity})
        source = ("illustrative defaults — create config/cost_model.yaml to use "
                  "your own figures" if self.model.from_defaults
                  else "config/cost_model.yaml")
        basis = (f"{affected} affected consumer(s) ({shape}) x "
                 f"${per_hour:,.0f}/hr x {self.model.assumed_mttr_hours:g}h assumed "
                 f"MTTR x {severity:g} severity ({change_type}) [{source}]")

        return CostEstimate(dollars=dollars,
                            hours_at_risk=self.model.assumed_mttr_hours,
                            breakdown=breakdown, basis=basis)
