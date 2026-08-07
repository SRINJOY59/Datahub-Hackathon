"""One place that reads the MLflow model registry.

Four detectors need the champion's metrics — the regression detector, the leakage
detector, the training/serving-skew detector, and the model-eval check — and the
Time Machine needs to know which older version is safe to roll back to. Reading
the registry once, here, keeps their notions of "the current model" identical.

Every method degrades to None / empty rather than raising: MLflow may not be
initialised yet on a fresh clone, and that is not an incident.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Below this the champion has regressed; above it, the score is too good to be
# true and suggests the label leaked into a feature. Both are incidents.
ROC_AUC_MIN = 0.65
ROC_AUC_MAX = 0.985

VALIDATED_TAG = "validation_status"
VALIDATED_VALUE = "passed"


@dataclass
class ModelVersionInfo:
    version: str
    run_id: str
    metrics: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)

    @property
    def roc_auc(self) -> Optional[float]:
        return self.metrics.get("roc_auc")

    @property
    def validated(self) -> bool:
        return self.tags.get(VALIDATED_TAG) == VALIDATED_VALUE

    @property
    def healthy(self) -> bool:
        roc = self.roc_auc
        return roc is not None and ROC_AUC_MIN <= roc <= ROC_AUC_MAX


class ChampionMetrics:
    """Read-only view of the model registry."""

    def __init__(self, model_name: str | None = None,
                 alias: str | None = None,
                 tracking_uri: str | None = None) -> None:
        from ml.config import CHAMPION_ALIAS, MLFLOW_TRACKING_URI, MODEL_NAME

        self.model_name = model_name or MODEL_NAME
        self.alias = alias or CHAMPION_ALIAS
        self.tracking_uri = tracking_uri or MLFLOW_TRACKING_URI

    # ------------------------------------------------------------------ #
    def _client(self):
        import mlflow

        mlflow.set_tracking_uri(self.tracking_uri)
        return mlflow.MlflowClient()

    def _info(self, client, mv) -> ModelVersionInfo:
        try:
            metrics = client.get_run(mv.run_id).data.metrics
        except Exception:
            metrics = {}
        return ModelVersionInfo(version=str(mv.version), run_id=mv.run_id,
                                metrics=dict(metrics), tags=dict(mv.tags or {}))

    # ------------------------------------------------------------------ #
    def current(self) -> Optional[ModelVersionInfo]:
        """The version the `champion` alias currently points at."""
        try:
            client = self._client()
            mv = client.get_model_version_by_alias(self.model_name, self.alias)
            return self._info(client, mv)
        except Exception:
            return None

    def all_versions(self) -> list[ModelVersionInfo]:
        try:
            client = self._client()
            versions = client.search_model_versions(f"name='{self.model_name}'")
            return sorted((self._info(client, v) for v in versions),
                          key=lambda i: int(i.version))
        except Exception:
            return []

    def last_good(self, exclude_version: str | None = None) -> Optional[ModelVersionInfo]:
        """The newest version worth rolling back to: explicitly validated and with
        metrics in the healthy band. Excluding the current champion means a
        rollback always moves somewhere, never to itself."""
        candidates = [
            v for v in self.all_versions()
            if v.validated and v.healthy and v.version != exclude_version
        ]
        return max(candidates, key=lambda v: int(v.version)) if candidates else None

    def training_feature_means(self,
                               info: Optional[ModelVersionInfo] = None) -> dict[str, float]:
        """Per-feature means logged at training time, for training/serving-skew
        comparison. Empty until ml/train.py logs them."""
        info = info or self.current()
        if not info:
            return {}
        prefix = "train_mean_"
        return {k[len(prefix):]: v for k, v in info.metrics.items()
                if k.startswith(prefix)}

    # ------------------------------------------------------------------ #
    def set_alias(self, version: str) -> bool:
        """Move the alias. This is the actual mitigation for a bad model."""
        try:
            self._client().set_registered_model_alias(
                self.model_name, self.alias, version
            )
            return True
        except Exception:
            return False
