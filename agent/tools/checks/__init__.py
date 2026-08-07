"""Importing this package registers all validation checks (decorators run on
import).

Several checks apply to one asset and their verdicts are ANDed, because no single
source is sufficient: dbt sees broken values, the model check sees a bad
champion, and the invariant check sees the silent failures that leave both of
them green.
"""
from agent.tools.checks import (  # noqa: F401
    data_invariants,
    dbt_checks,
    model_checks,
)
