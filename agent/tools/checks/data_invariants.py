"""Check: the invariants no dbt test covers.

Some failures leave every assertion green. A feed that stops delivering, or a
batch that arrives at a tenth of its usual size, contains no nulls, violates no
range, and duplicates nothing — dbt is perfectly happy and the pipeline is
quietly wrong. Without this check the validation gate would certify a mitigation
that fixed nothing, and the agent would close a live incident.

Both invariants are measured against the recorded healthy baseline rather than
against wall-clock time or a fixed row count, because "normal" is a property of
this pipeline, not a universal constant.
"""
from __future__ import annotations

from datetime import datetime

from agent.contracts import ValidationResult
from agent.registry import check
from agent.tools.graph.urns import is_dataset
from agent.tools.warehouse.baselines import BaselineStore

# A drop this large is a collapse, not natural variation.
VOLUME_DROP_TOLERANCE = 0.25
# Growth this large usually means a batch was delivered more than once.
VOLUME_GROWTH_TOLERANCE = 0.50
# How far the newest row may fall behind where the baseline left it.
FRESHNESS_MAX_LAG_HOURS = 24.0


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


@check
class DataInvariantCheck:
    name = "data_invariants"

    def __init__(self, gms_server: str = "http://localhost:8080") -> None:
        self.baselines = BaselineStore()

    def applies_to(self, asset_urn: str) -> bool:
        return is_dataset(asset_urn)

    def run(self, asset_urn: str) -> ValidationResult:
        baseline = self.baselines.load()
        if not baseline:
            # Never assert health we cannot actually evidence.
            return ValidationResult(
                passed=True, checks_run=["volume", "freshness"],
                failures=[],
            )

        current = self.baselines.current()
        checks: list[str] = []
        failures: list[str] = []

        for table, base in sorted(baseline.items()):
            now = current.get(table)
            if now is None:
                failures.append(f"volume[{table}]: table has disappeared")
                continue

            checks.append(f"volume[{table}]")
            failures.extend(self._volume_failure(table, base, now))

            if base.max_timestamp:
                checks.append(f"freshness[{table}]")
                failures.extend(self._freshness_failure(table, base, now))

        return ValidationResult(passed=not failures, checks_run=checks,
                                failures=failures)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _volume_failure(table, base, now) -> list[str]:
        if not base.row_count:
            return []
        shift = (now.row_count - base.row_count) / base.row_count
        if shift <= -VOLUME_DROP_TOLERANCE:
            return [f"volume[{table}]: {now.row_count} rows vs {base.row_count} "
                    f"baseline ({shift:+.0%}) — the feed collapsed"]
        if shift >= VOLUME_GROWTH_TOLERANCE:
            return [f"volume[{table}]: {now.row_count} rows vs {base.row_count} "
                    f"baseline ({shift:+.0%}) — looks like a re-delivered batch"]
        return []

    @staticmethod
    def _freshness_failure(table, base, now) -> list[str]:
        base_ts, now_ts = _parse(base.max_timestamp), _parse(now.max_timestamp)
        if base_ts is None:
            return []
        if now_ts is None:
            return [f"freshness[{table}]: no timestamped rows remain"]
        # Newer than baseline is the healthy direction and never a failure.
        lag_hours = (base_ts - now_ts).total_seconds() / 3600.0
        if lag_hours > FRESHNESS_MAX_LAG_HOURS:
            return [f"freshness[{table}]: newest row is {lag_hours:.0f}h behind "
                    f"the baseline ({now.max_timestamp} vs {base.max_timestamp})"]
        return []
