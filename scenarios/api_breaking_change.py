"""API/dependency breaking-change incident ("self-maintaining APIs").

Publishes a vendor advisory for scikit-learn (a package the ML training code
actually uses). The dependency detector picks it up, scans the codebase for
affected usages, traces them to the impacted DataHub model, and the agent opens a
migration PR — applying the change instead of just announcing it.
"""
from __future__ import annotations

from scenarios.base import AdvisoryScenario


class ApiBreakingChangeScenario(AdvisoryScenario):
    name = "api_breaking_change"
    description = "Vendor ships a breaking scikit-learn API change"

    advisory = {
        "package": "scikit-learn",
        "import_name": "sklearn",
        "from_version": "1.9.0",
        "to_version": "2.0.0",
        "kind": "breaking_change",
        "summary": ("GradientBoostingClassifier's `n_estimators` argument was "
                    "renamed to `num_estimators` in scikit-learn 2.0."),
        "migration": ("Rename the `n_estimators` keyword argument to "
                      "`num_estimators` wherever GradientBoostingClassifier is "
                      "constructed."),
        "symbols": ["GradientBoostingClassifier", "n_estimators"],
    }
