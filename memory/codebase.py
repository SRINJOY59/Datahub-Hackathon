"""CodebaseMemory — a queryable index of the repository, so the agent can reason
about code and dependency changes, not just data.

It answers, for any incident that originates in code rather than in the warehouse:

  * which files import a package, define a symbol, or use a name
  * which DataHub asset a source file produces — and the inverse
  * which files are pipeline sources at all (the git-commit detector's scope)

Indexing is AST-based where it can be — robust to multi-line imports, aliases and
relative imports, and able to see the functions and classes a file defines, which
a line-by-line regex cannot. Files that don't parse (or aren't Python) fall back
to a line scan. The index and the file contents are read once and cached, and
`shared_codebase()` hands every probe and detector the same instance, so the repo
is read once per run rather than once per tool.

The producer map — source file → the DataHub asset it produces — is kept explicit
because the link from a file to a catalogued asset is a fact about this project,
not something reliably inferable from paths alone.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import datahub.emitter.mce_builder as builder

REPO_ROOT = Path(__file__).resolve().parents[1]
_SKIP = {".venv", "mlruns", "mlartifacts", "target", "__pycache__", ".git",
         "dbt_packages", ".sentinel", "examples"}
_SOURCE_GLOBS = ("*.py", "*.sql")
_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z0-9_\.]+)")

ENV = "PROD"
_MODEL_URN = builder.make_ml_model_urn("mlflow", "fraud_detection_model_1", ENV)
_DEPLOY_URN = builder.make_ml_model_deployment_urn("mlflow", "fraud_scoring_api", ENV)
_DBT_NAME_PREFIX = "fraud_demo.fraud.main"   # the dbt schema this project ingests under


def _dataset_urn(table: str) -> str:
    return builder.make_dataset_urn("dbt", f"{_DBT_NAME_PREFIX}.{table}", ENV)


@dataclass
class Usage:
    file: str
    line_no: int
    line: str


@dataclass
class FileFacts:
    """What one source file imports and defines (top-level)."""
    imports: set[str] = field(default_factory=set)   # top-level package names
    defines: set[str] = field(default_factory=set)   # top-level function/class names


class CodebaseMemory:
    def __init__(self, repo_root: Path | str = REPO_ROOT) -> None:
        self.root = Path(repo_root)
        self._lines: dict[str, list[str]] = {}       # relpath -> cached lines
        self._facts: dict[str, FileFacts] = {}       # relpath -> imports/defines (py)
        self._producers: dict[str, str] = {}         # relpath -> asset urn
        self._producer_rev: dict[str, str] = {}      # asset urn -> relpath
        self._build()

    # ------------------------------------------------------------------ #
    # indexing
    # ------------------------------------------------------------------ #
    def _iter_sources(self):
        for glob in _SOURCE_GLOBS:
            for p in self.root.rglob(glob):
                if not any(part in _SKIP for part in p.parts):
                    yield p

    def _build(self) -> None:
        for p in self._iter_sources():
            rel = p.relative_to(self.root).as_posix()
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            self._lines[rel] = text.splitlines()
            if p.suffix == ".py":
                self._facts[rel] = _index_python(text)
        self._build_producers()
        self._producer_rev = {urn: rel for rel, urn in self._producers.items()}

    def _build_producers(self) -> None:
        """Source file -> the DataHub asset it produces."""
        self._producers["ml/train.py"] = _MODEL_URN
        self._producers["ml/score.py"] = _DEPLOY_URN
        self._producers["pipeline/generate_raw_data.py"] = _dataset_urn("raw_transactions")

        models_dir = self.root / "pipeline" / "dbt" / "models"
        for sql in models_dir.rglob("*.sql"):
            self._producers[sql.relative_to(self.root).as_posix()] = _dataset_urn(sql.stem)

        seeds_dir = self.root / "pipeline" / "dbt" / "seeds"
        for seed in seeds_dir.rglob("*.csv"):
            self._producers[seed.relative_to(self.root).as_posix()] = _dataset_urn(seed.stem)

    # ------------------------------------------------------------------ #
    # imports / symbols
    # ------------------------------------------------------------------ #
    def files_importing(self, package: str) -> list[str]:
        pkg = package.split(".")[0]
        return [rel for rel, f in self._facts.items() if pkg in f.imports]

    def defines(self, symbol: str) -> list[str]:
        """Files that define a given top-level function or class."""
        return [rel for rel, f in self._facts.items() if symbol in f.defines]

    def symbols_in(self, rel_path: str) -> set[str]:
        facts = self._facts.get(rel_path)
        return set(facts.defines) if facts else set()

    def all_packages(self) -> set[str]:
        """Every top-level package imported anywhere in the repo."""
        out: set[str] = set()
        for f in self._facts.values():
            out |= f.imports
        return out

    def usages(self, symbols: list[str]) -> list[Usage]:
        """Every line (across all cached source files) mentioning any symbol."""
        pats = [re.compile(re.escape(s)) for s in symbols if s]
        if not pats:
            return []
        out: list[Usage] = []
        for rel, lines in self._lines.items():
            for i, line in enumerate(lines, 1):
                if any(p.search(line) for p in pats):
                    out.append(Usage(rel, i, line.strip()))
        return out

    # ------------------------------------------------------------------ #
    # the producer map, read both ways
    # ------------------------------------------------------------------ #
    def impacted_assets(self, package: str) -> list[str]:
        """DataHub asset urns produced by files importing `package`."""
        assets = [self._producers[rel] for rel in self.files_importing(package)
                  if rel in self._producers]
        return list(dict.fromkeys(assets))  # dedupe, preserve order

    def producer_of(self, rel_path: str) -> Optional[str]:
        """The DataHub asset urn a source file produces, if any."""
        return self._producers.get(rel_path)

    def source_file_for(self, asset_urn: str) -> Optional[str]:
        """The source file that produces an asset — the inverse of the producer
        map, precomputed so it is a dict lookup rather than a scan. Turns 'the
        root cause is raw_transactions.amount' into 'the root cause is this file',
        which git then resolves to a commit."""
        return self._producer_rev.get(asset_urn)

    def source_files(self) -> dict[str, str]:
        """The whole producer map, file -> asset urn (a copy)."""
        return dict(self._producers)

    def pipeline_source_files(self) -> list[str]:
        """Every file that produces a DataHub asset — the set a commit has to
        touch to be worth raising as a code-change incident."""
        return list(self._producers)


# --------------------------------------------------------------------------- #
def _index_python(text: str) -> FileFacts:
    """Top-level imports and definitions via the AST, with a regex fallback for
    files that don't parse (a syntax error is itself a code problem, and losing
    the whole index over one bad file would be worse)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _index_python_regex(text)

    facts = FileFacts()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                facts.imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            facts.imports.add(node.module.split(".")[0])
    for node in tree.body:  # only top-level defs are "the file's" symbols
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            facts.defines.add(node.name)
    return facts


def _index_python_regex(text: str) -> FileFacts:
    facts = FileFacts()
    for line in text.splitlines():
        m = _IMPORT_RE.match(line)
        if m:
            facts.imports.add(m.group(1).split(".")[0])
    return facts


_SHARED: Optional[CodebaseMemory] = None


def shared_codebase() -> CodebaseMemory:
    """One index per process. Probes and detectors share it so the repo is read
    once per run rather than once per tool."""
    global _SHARED
    if _SHARED is None:
        _SHARED = CodebaseMemory()
    return _SHARED
