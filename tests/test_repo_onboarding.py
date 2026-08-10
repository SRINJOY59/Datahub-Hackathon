"""Unit tests for Enterprise Repository Onboarding & AST Lineage Engine."""
import pytest
from pathlib import Path
from api.repo_onboarding import (
    GitSandbox,
    PipelineASTVisitor,
    CodebasePipelineScanner,
    ConnectedRepoStore,
    onboard_repository,
)


def test_git_sandbox_local():
    path, name, sha = GitSandbox.resolve_repository(".")
    assert path.exists()
    assert len(name) > 0


def test_pipeline_ast_visitor():
    code = """
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
import mlflow

def train():
    df = pd.read_csv("data.csv")
    features = df[['amount', 'hour', 'merchant_id']]
    y = df['is_fraud']
    model = GradientBoostingClassifier(n_estimators=150, learning_rate=0.05)
    model.fit(features, y)
    mlflow.log_metric("accuracy", 0.96)
"""
    import ast
    tree = ast.parse(code)
    visitor = PipelineASTVisitor("ml/train.py", "fraud_detector")
    visitor.visit(tree)

    assert len(visitor.models) == 1
    assert visitor.models[0].algorithm == "GradientBoostingClassifier"
    assert visitor.models[0].framework == "scikit-learn"
    assert visitor.models[0].hyperparameters.get("n_estimators") == 150
    assert visitor.models[0].hyperparameters.get("learning_rate") == 0.05
    assert len(visitor.datasets) == 1
    assert "amount" in visitor.columns_referenced
    assert visitor.uses_mlflow is True


def test_connected_repo_store(tmp_path):
    db_path = tmp_path / "test_repos.db"
    store = ConnectedRepoStore(db_path)
    res = onboard_repository(".")
    store.save(res, {})
    repos = store.list()
    assert len(repos) >= 1
    assert repos[0]["repo_name"] == res.repo_name


def test_end_to_end_onboarding():
    res = onboard_repository(".")
    assert res.total_files_scanned > 0
    assert res.datasets_count > 0
    assert res.models_count > 0
    assert res.lineage_edges_count >= 2
    assert "name: Sentinel DataHub & ML Lineage Guard" in res.github_workflow_content
