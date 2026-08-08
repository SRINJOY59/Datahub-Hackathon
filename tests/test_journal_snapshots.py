"""The two things a rollback depends on: the record, and the copy.

If either of these is subtly wrong the agent will believe it can undo something
it cannot, which is worse than not acting at all.
"""
from __future__ import annotations

from agent.contracts import ActionRecord, ActionType
from agent.journal import APPLIED, REVERTED, SIMULATED, ActionJournal
from agent.policy import AutonomyPolicy


class TestActionJournal:
    def test_round_trip_preserves_the_inverse(self, journal):
        """The inverse is the whole point of the record; losing it in
        serialisation would leave an action that cannot be undone. Read back
        through the file rather than from memory, since that is the path a
        rollback after a crash actually takes."""
        record = ActionRecord(ActionType.QUARANTINE, "urn:x",
                              params={"table": "raw_transactions"})
        record.inverse = ActionRecord(ActionType.QUARANTINE, "urn:x",
                                      params={"restore_label": "pre_INC-1"})
        journal.record_applied(record, "INC-1")

        loaded = journal.entries()[0]
        assert loaded.action_type is ActionType.QUARANTINE
        assert loaded.incident_id == "INC-1"
        assert loaded.status == APPLIED
        assert loaded.inverse.params == {"restore_label": "pre_INC-1"}
        assert loaded.applied_at is not None

    def test_undo_runs_in_reverse(self, journal, action):
        """Actions may depend on each other, so unwinding is a stack."""
        journal.record_applied(action(ActionType.QUARANTINE), "INC-1")
        journal.record_applied(action(ActionType.PIN_FEATURE), "INC-1")
        journal.record_applied(action(ActionType.TAG_ASSET), "INC-1")

        order = []
        journal.undo_all("INC-1", lambda a: (order.append(a.action_type.value), True)[1])
        assert order == ["tag_asset", "pin_feature", "quarantine"]

    def test_reverted_actions_stop_counting_as_applied(self, journal, action):
        journal.record_applied(action(ActionType.PIN_FEATURE), "INC-1")
        journal.undo_all("INC-1", lambda a: True)
        assert journal.applied_for_incident("INC-1") == []
        assert any(e.status == REVERTED for e in journal.entries())

    def test_simulated_actions_were_never_applied(self, journal, action):
        """Shadow mode must not leave anything that looks undoable."""
        journal.record_simulated(action(ActionType.PIN_FEATURE), "INC-2")
        assert journal.applied_for_incident("INC-2") == []
        assert journal.entries()[0].status == SIMULATED

    def test_incidents_do_not_bleed_into_each_other(self, journal, action):
        journal.record_applied(action(ActionType.PIN_FEATURE, incident="INC-1"), "INC-1")
        journal.record_applied(action(ActionType.TAG_ASSET, incident="INC-2"), "INC-2")
        reverted, _ = journal.undo_all("INC-1", lambda a: True)
        assert reverted == 1
        assert len(journal.applied_for_incident("INC-2")) == 1

    def test_selective_undo_keeps_the_protection_up(self, journal, action):
        """A failed repair is a reason to keep warning people, not to stop."""
        journal.record_applied(action(ActionType.PIN_FEATURE), "INC-1")
        journal.record_applied(action(ActionType.TAG_ASSET), "INC-1")
        journal.record_applied(action(ActionType.PAUSE_JOB), "INC-1")

        reverted, failed = journal.undo_all(
            "INC-1", lambda a: True,
            only=lambda a: not AutonomyPolicy.is_protective(a.action_type))
        assert (reverted, failed) == (1, 0)
        still_up = {e.action_type for e in journal.applied_for_incident("INC-1")}
        assert still_up == {ActionType.TAG_ASSET, ActionType.PAUSE_JOB}

    def test_a_failed_undo_is_counted_not_swallowed(self, journal, action):
        journal.record_applied(action(ActionType.PIN_FEATURE), "INC-1")
        reverted, failed = journal.undo_all("INC-1", lambda a: False)
        assert (reverted, failed) == (0, 1)

    def test_a_raising_undo_does_not_abort_the_rollback(self, journal, action):
        journal.record_applied(action(ActionType.PIN_FEATURE), "INC-1")
        journal.record_applied(action(ActionType.TAG_ASSET), "INC-1")
        boom = lambda a: (_ for _ in ()).throw(RuntimeError("nope"))  # noqa: E731
        reverted, failed = journal.undo_all(
            "INC-1", lambda a: boom(a) if a.action_type is ActionType.TAG_ASSET else True)
        assert (reverted, failed) == (1, 1)

    def test_a_torn_line_does_not_make_the_journal_unreadable(self, journal, action):
        journal.record_applied(action(ActionType.PIN_FEATURE), "INC-1")
        with journal.path.open("a", encoding="utf-8") as fh:
            fh.write('{"action_type": "pin_feat\n')
        assert len(journal.entries()) == 1

    def test_missing_journal_is_empty_not_an_error(self, tmp_path):
        assert ActionJournal(tmp_path / "absent.jsonl").entries() == []


class TestSnapshotStore:
    def test_restore_is_exact(self, temp_duckdb):
        """Verified by content fingerprint, not row count: a restore that brings
        back the right number of wrong rows is not a restore."""
        import duckdb

        from agent.tools.warehouse.snapshots import SnapshotStore

        store = SnapshotStore(temp_duckdb)
        before = store.fingerprint("raw_transactions")
        assert store.capture("raw_transactions", "last_good")

        con = duckdb.connect(temp_duckdb)
        con.execute("update raw_transactions set amount = amount * 100 "
                    "where transaction_id > 150")
        con.execute("delete from raw_transactions where transaction_id < 10")
        con.close()
        assert store.fingerprint("raw_transactions") != before

        assert store.restore("raw_transactions", "last_good")
        assert store.fingerprint("raw_transactions") == before

    def test_views_are_not_snapshotted(self, temp_duckdb):
        """A view has no state of its own, and replacing one with a table would
        break the next dbt run."""
        import duckdb

        from agent.tools.warehouse.snapshots import SnapshotStore

        con = duckdb.connect(temp_duckdb)
        con.execute("create view v as select * from raw_transactions")
        con.close()
        assert SnapshotStore(temp_duckdb).base_tables() == ["raw_transactions"]

    def test_it_refuses_to_restore_what_it_never_captured(self, temp_duckdb):
        from agent.tools.warehouse.snapshots import SnapshotStore

        assert SnapshotStore(temp_duckdb).restore("raw_transactions", "nope") is False

    def test_per_action_labels_do_not_collide(self, temp_duckdb):
        """Two warehouse actuators in one plan both snapshot the same table. A
        shared label meant the second overwrote the first's way back."""
        import duckdb

        from agent.tools.warehouse.snapshots import SnapshotStore

        store = SnapshotStore(temp_duckdb)
        store.capture("raw_transactions", "pre_INC-1_quarantine")
        con = duckdb.connect(temp_duckdb)
        con.execute("delete from raw_transactions where transaction_id < 50")
        con.close()
        store.capture("raw_transactions", "pre_INC-1_pin_feature")

        assert store.row_count("raw_transactions", "pre_INC-1_quarantine") == 200
        assert store.row_count("raw_transactions", "pre_INC-1_pin_feature") == 150

    def test_incident_snapshots_are_dropped_but_the_baseline_survives(self, temp_duckdb):
        from agent.tools.warehouse.snapshots import SnapshotStore

        store = SnapshotStore(temp_duckdb)
        store.capture("raw_transactions", "last_good")
        store.capture("raw_transactions", "pre_INC-1_pin_feature")
        assert store.drop_incident_snapshots() == 1
        assert store.exists("raw_transactions", "last_good")
        assert not store.exists("raw_transactions", "pre_INC-1_pin_feature")
