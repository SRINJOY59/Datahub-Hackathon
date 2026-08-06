"""Schema-change incident: an upstream rename drops the `amount` column (renamed
to `amount_cents`), so the feature that reads it goes null/absent.
"""
from __future__ import annotations

import duckdb

from scenarios.base import Scenario


class SchemaChangeScenario(Scenario):
    name = "schema_change"
    description = "Upstream renames the amount column (schema drift)"

    def inject(self, con: duckdb.DuckDBPyConnection) -> str:
        # rename amount -> amount_cents: the downstream models still read `amount`,
        # which now resolves to NULL for the whole table.
        con.execute("alter table raw_transactions rename column amount to amount_cents")
        # keep a NULL `amount` column so dbt still compiles but values are gone
        con.execute("alter table raw_transactions add column amount double")
        return ("upstream renamed `amount` -> `amount_cents`; the `amount` column "
                "the pipeline reads is now empty (schema change)")
