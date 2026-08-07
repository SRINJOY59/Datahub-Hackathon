"""Check: is the model being asked about the world it was trained on?

`ModelEvalCheck` asks whether the model is any good. That is not the same
question as whether it is safe to serve, and conflating them makes the gate blind
in exactly the case that matters most: when the model is fine and its *inputs*
have moved, `roc_auc` is unchanged and every other check passes while the
predictions quietly stop meaning what they used to.

Without this, a skew or drift incident would validate green immediately after
mitigation and the agent would declare victory over a problem it had only
contained.

Both comparisons reuse the same code the detectors use, so the gate cannot
disagree with the thing that raised the incident.
"""
from __future__ import annotations

from agent.contracts import ValidationResult
from agent.registry import check
from agent.tools.detectors.model_drift import BASELINE_PATH, SNAPSHOT_PATH, _load
from agent.tools.detectors.training_serving_skew import SKEW_TOLERANCE
from agent.tools.graph.urns import is_model
from agent.tools.warehouse.champion import ChampionMetrics
from ml.drift import compute_drift, relative_shift


@check
class ModelInputCheck:
    name = "model_inputs"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.champion = ChampionMetrics()

    def applies_to(self, asset_urn: str) -> bool:
        return is_model(asset_urn)

    def run(self, asset_urn: str) -> ValidationResult:
        checks: list[str] = []
        failures: list[str] = []

        snapshot, baseline = _load(SNAPSHOT_PATH), _load(BASELINE_PATH)
        if snapshot and baseline:
            checks.append("prediction_drift")
            report = compute_drift(snapshot, baseline)
            if report.drifted:
                failures.append(f"prediction_drift: {report.summary()}")

        failures.extend(self._skew_failures(snapshot, checks))

        return ValidationResult(passed=not failures, checks_run=checks,
                                failures=failures)

    # ------------------------------------------------------------------ #
    def _skew_failures(self, snapshot: dict, checks: list[str]) -> list[str]:
        info = self.champion.current()
        if info is None:
            return []
        train = self.champion.training_feature_means(info)
        serve = (snapshot or {}).get("feature_means") or {}
        if not train or not serve:
            return []

        checks.append("training_serving_skew")
        skewed = {
            f: relative_shift(serve[f], train[f])
            for f in train if f in serve
            and abs(relative_shift(serve[f], train[f])) >= SKEW_TOLERANCE
        }
        if not skewed:
            return []
        worst = max(skewed, key=lambda f: abs(skewed[f]))
        return [f"training_serving_skew: {len(skewed)} feature(s) outside "
                f"{SKEW_TOLERANCE:.0%} of champion v{info.version}'s training "
                f"distribution (worst: {worst} {skewed[worst]:+.0%})"]
