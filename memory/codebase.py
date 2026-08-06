"""CodebaseMemory — indexes the repo so the agent can reason about code and
dependency changes, not just data.

It answers:
  * which files import a given package  (files_importing)
  * where a symbol is used, file+line     (usages)
  * which DataHub assets a code/dependency change impacts (impacted_assets)

The producer map links source files to the DataHub asset they produce, which is
what lets a `transformers`/`sklearn` upgrade be traced to the ML model it breaks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import datahub.emitter.mce_builder as builder

REPO_ROOT = Path(__file__).resolve().parents[1]
_SKIP = {".venv", "mlruns", "mlartifacts", "target", "__pycache__", ".git",
         "dbt_packages", ".sentinel", "examples"}
_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z0-9_\.]+)")

ENV = "PROD"
_MODEL_URN = builder.make_ml_model_urn("mlflow", "fraud_detection_model_1", ENV)
_DEPLOY_URN = builder.make_ml_model_deployment_urn("mlflow", "fraud_scoring_api", ENV)


def _dataset_urn(table: str) -> str:
    return builder.make_dataset_urn("dbt", f"fraud_demo.fraud.main.{table}", ENV)


@dataclass
class Usage:
    file: str
    line_no: int
    line: str


class CodebaseMemory:
    def __init__(self, repo_root: Path | str = REPO_ROOT) -> None:
        self.root = Path(repo_root)
        self._imports: dict[str, set[str]] = {}   # relpath -> top-level modules
        self._producers: dict[str, str] = {}      # relpath -> asset urn
        self._index()

    # ------------------------------------------------------------------ #
    def _py_files(self):
        for p in self.root.rglob("*.py"):
            if any(part in _SKIP for part in p.parts):
                continue
            yield p

    def _index(self) -> None:
        for p in self._py_files():
            rel = p.relative_to(self.root).as_posix()
            mods: set[str] = set()
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    m = _IMPORT_RE.match(line)
                    if m:
                        mods.add(m.group(1).split(".")[0])
            except OSError:
                continue
            self._imports[rel] = mods

        # declared code -> DataHub asset producer map
        self._producers["ml/train.py"] = _MODEL_URN
        self._producers["ml/score.py"] = _DEPLOY_URN
        for sql in (self.root / "pipeline" / "dbt" / "models").rglob("*.sql"):
            rel = sql.relative_to(self.root).as_posix()
            self._producers[rel] = _dataset_urn(sql.stem)

    # ------------------------------------------------------------------ #
    def files_importing(self, package: str) -> list[str]:
        pkg = package.split(".")[0]
        return [rel for rel, mods in self._imports.items() if pkg in mods]

    def usages(self, symbols: list[str]) -> list[Usage]:
        out: list[Usage] = []
        pats = [re.compile(re.escape(s)) for s in symbols if s]
        for p in self._py_files():
            rel = p.relative_to(self.root).as_posix()
            try:
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if any(pat.search(line) for pat in pats):
                    out.append(Usage(rel, i, line.strip()))
        return out

    def impacted_assets(self, package: str) -> list[str]:
        """DataHub asset urns produced by files importing `package`."""
        assets: list[str] = []
        for rel in self.files_importing(package):
            if rel in self._producers:
                assets.append(self._producers[rel])
        # dedupe, preserve order
        return list(dict.fromkeys(assets))
