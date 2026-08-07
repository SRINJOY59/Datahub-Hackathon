"""Trying a fix somewhere it cannot hurt anyone.

Two things the live validation gate structurally cannot check:

  * **a candidate model**, because finding out whether v4 behaves better than v5
    by pointing production at it and watching is not an experiment, it is an
    outage. Here the candidate is loaded and scored against the current features
    with the alias left untouched, so the comparison costs nothing.

  * **a generated code fix**, because the gate re-runs the pipeline as it is on
    disk, and a proposed diff has not been applied. An LLM-written file that does
    not even parse should never reach a human as a suggestion.

Neither writes to anything real. The point is to have a before-and-after to show
rather than an assurance to give.
"""
from __future__ import annotations

import ast
from typing import Optional

import pandas as pd

from agent.contracts import ShadowResult
from agent.tools.warehouse.duck import connect
from ml.config import DUCKDB_PATH, FEATURES, MODEL_NAME, MLFLOW_TRACKING_URI


class ShadowEnvironment:
    """Evaluates candidates without changing production."""

    def __init__(self, duckdb_path: str | None = None) -> None:
        self.duckdb_path = str(duckdb_path or DUCKDB_PATH)

    # ------------------------------------------------------------------ #
    def current_features(self) -> Optional[pd.DataFrame]:
        """Today's features, restricted to rows a model can actually score.

        Incomplete rows are dropped rather than allowed to fail the comparison.
        A model rollback is evaluated *during* an incident, which is precisely
        when the data is likely to have holes in it — a preview that only works
        on healthy data would be unavailable exactly when it is needed.
        """
        con = connect(self.duckdb_path, read_only=True)
        try:
            frame = con.execute(
                f"select {', '.join(FEATURES)} from training_dataset"
            ).df()
        except Exception:
            return None
        finally:
            con.close()
        return frame.dropna()

    def score_version(self, version: str) -> dict:
        """What a given model version would predict on today's data.

        Loaded by version rather than by alias, so the champion pointer is never
        involved and this can be run against a model nobody has promoted.
        """
        try:
            import mlflow
            import mlflow.sklearn

            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/{version}")
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

        X = self.current_features()
        if X is None or X.empty:
            return {"error": "no features available to score"}

        try:
            proba = model.predict_proba(X)[:, 1]
        except Exception as e:
            return {"error": f"model could not score current features: {e}"}

        return {
            "version": version,
            "n_scored": int(len(X)),
            "positive_pred_rate": float((proba >= 0.5).mean()),
            "mean_score": float(proba.mean()),
        }

    def compare_versions(self, current: str, candidate: str) -> ShadowResult:
        """Score both versions side by side on identical data."""
        before = self.score_version(current)
        after = self.score_version(candidate)

        failures = [m["error"] for m in (before, after) if "error" in m]
        if failures:
            return ShadowResult(passed=False, checks_run=["candidate_scores"],
                                failures=failures, metrics_before=before,
                                metrics_after=after,
                                note="could not evaluate the candidate")

        delta = after["positive_pred_rate"] - before["positive_pred_rate"]
        return ShadowResult(
            passed=True,
            checks_run=["candidate_scores"],
            metrics_before=before,
            metrics_after=after,
            note=(f"v{candidate} would flag {after['positive_pred_rate']:.4f} of "
                  f"transactions vs v{current}'s {before['positive_pred_rate']:.4f} "
                  f"({delta:+.4f}) on the same {after['n_scored']} rows"),
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def verify_python(filename: str, content: str) -> ShadowResult:
        """Does the proposed file actually parse?

        The cheapest possible sanity check, and the one that catches the failure
        mode that matters: a model that returns confident, well-formatted,
        syntactically broken Python. Parsing is not proof the fix is correct, so
        the note says exactly what was and was not established.
        """
        try:
            ast.parse(content, filename=filename)
        except SyntaxError as e:
            return ShadowResult(
                passed=False, checks_run=["syntax"],
                failures=[f"{filename}: line {e.lineno}: {e.msg}"],
                note="the generated fix is not valid Python — not proposing it",
            )
        return ShadowResult(
            passed=True, checks_run=["syntax"],
            note=f"{filename} parses; syntax verified, behaviour not",
        )
