"""Schema-change incident: an upstream rename drops the `amount` column (renamed
to `amount_cents`), so the feature that reads it goes null/absent.
"""
from __future__ import annotations

import duckdb

from scenarios.base import DataScenario, Expectation


class SchemaChangeScenario(DataScenario):
    name = "schema_change"
    description = "Upstream renames the amount column (schema drift)"

    expectation = Expectation(
        signal_type="assertion_failure",
        change_type="schema_change",
        root_table="raw_transactions",
        root_column="amount",
        actions=["pin_feature", "tag_asset"],
    )

    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        cols = [r[0] for r in con.execute(
            "select column_name from information_schema.columns "
            "where table_name = 'raw_transactions'"
        ).fetchall()]

        if "amount_cents" in cols and "amount" in cols:
            con.execute("alter table raw_transactions drop column amount")
            con.execute("alter table raw_transactions add column amount double")
        elif "amount_cents" in cols:
            con.execute("alter table raw_transactions add column amount double")
        elif "amount" in cols:
            con.execute("alter table raw_transactions rename column amount to amount_cents")
            con.execute("alter table raw_transactions add column amount double")

        return ("upstream renamed `amount` -> `amount_cents`; the `amount` column "
                "the pipeline reads is now empty (schema change)")
