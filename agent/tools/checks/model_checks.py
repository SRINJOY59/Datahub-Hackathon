"""Check: is the model currently serving fit to serve?

Bounded on both sides. A score below the floor means the champion regressed; a
score above the ceiling is too good to be true and usually means the label leaked
into a feature. A gate that only checked the floor would happily certify a model
that had learned to read the answer.
"""
from __future__ import annotations

from agent.contracts import ValidationResult
from agent.registry import check
from agent.tools.graph.urns import is_model
from agent.tools.warehouse.champion import ROC_AUC_MAX, ROC_AUC_MIN, ChampionMetrics


@check
class ModelEvalCheck:
    name = "model_eval"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.champion = ChampionMetrics()

    def applies_to(self, asset_urn: str) -> bool:
        return is_model(asset_urn)

    def run(self, asset_urn: str) -> ValidationResult:
        info = self.champion.current()
        if info is None:
            return ValidationResult(
                passed=False, checks_run=["champion_reachable"],
                failures=["champion_reachable: no champion model in the registry"],
            )

        roc = info.roc_auc
        checks = [f"roc_auc_within[{ROC_AUC_MIN},{ROC_AUC_MAX}]"]
        if roc is None:
            return ValidationResult(passed=False, checks_run=checks,
                                    failures=["roc_auc: not logged for this run"])
        if roc < ROC_AUC_MIN:
            return ValidationResult(
                passed=False, checks_run=checks,
                failures=[f"roc_auc {roc:.3f} below floor {ROC_AUC_MIN} "
                          f"(champion v{info.version} regressed)"],
            )
        if roc > ROC_AUC_MAX:
            return ValidationResult(
                passed=False, checks_run=checks,
                failures=[f"roc_auc {roc:.3f} above ceiling {ROC_AUC_MAX} "
                          f"(champion v{info.version} — suspect label leakage)"],
            )
        return ValidationResult(passed=True, checks_run=checks)
