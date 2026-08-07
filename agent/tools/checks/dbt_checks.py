"""Check: re-run the warehouse's own assertions.

The primary validation gate for data assets — if a mitigation worked, the tests
that flagged the incident should now pass. Reports assertions by name so a
failure says *which* invariant is still broken, not just that something is.
"""
from __future__ import annotations

from agent.contracts import ValidationResult
from agent.registry import check
from agent.tools.graph.urns import is_dataset
from agent.tools.warehouse.dbt_runner import DbtRunner


@check
class DbtTestCheck:
    name = "dbt_tests"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.dbt = DbtRunner()

    def applies_to(self, asset_urn: str) -> bool:
        return is_dataset(asset_urn)

    def run(self, asset_urn: str) -> ValidationResult:
        # The whole suite, not just this asset's tests: a mitigation upstream can
        # break something sideways, and a gate that only looks where it already
        # knows to look would miss it.
        result = self.dbt.test()
        return ValidationResult(
            passed=result.ok,
            checks_run=result.passed + result.failed,
            failures=result.failed,
        )
