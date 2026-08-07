"""Shared fixtures.

Everything here runs offline: no DataHub, no MLflow, no API key, and no reliance
on the project's DuckDB file. Tests that need a warehouse build a throwaway one,
so running the suite can never disturb the pipeline you are demoing with.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def temp_duckdb(tmp_path):
    """A small warehouse with the shape the real one has: a timestamped source
    table with a key, an amount, and a label."""
    import duckdb

    path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "create table raw_transactions as "
        "select i as transaction_id, "
        "       (i % 50) + 1.0 as amount, "
        "       (i % 10 = 0)::int as is_fraud, "
        "       timestamp '2026-01-01' + interval (i) hour as txn_timestamp "
        "from range(200) t(i)"
    )
    con.close()
    return str(path)


@pytest.fixture
def journal(tmp_path):
    from agent.journal import ActionJournal

    return ActionJournal(tmp_path / "journal.jsonl")


@pytest.fixture
def action():
    """A reversible action, shaped the way an actuator returns one."""
    from agent.contracts import ActionRecord, ActionType

    def build(action_type=ActionType.PIN_FEATURE, target="urn:table:x",
              incident="INC-1", **params):
        rec = ActionRecord(action_type, target, params=params,
                           incident_id=incident)
        rec.inverse = ActionRecord(action_type, target,
                                   params={"restore_label": "pre_INC-1"})
        return rec

    return build
