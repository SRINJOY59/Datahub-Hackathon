"""Importing this package registers all actuators (decorators run on import).

Actuators are dispatched by ActionType. Two families:

  * warehouse actuators (pin, quarantine, dedupe) rewrite tables, and inherit
    snapshot-then-mutate-then-rebuild from WarehouseActuator;
  * control actuators (repoint, tag, pause) change a pointer, a label, or a
    breaker file, and are undone by changing it back.

Every one of them records the inverse that undoes it. That is the property the
whole autonomy story depends on, so it belongs to the base class rather than to
each author's discipline.
"""
from agent.tools.actuators import (  # noqa: F401
    dedupe,
    pause_job,
    pin_feature,
    quarantine,
    repoint_model,
    tag_asset,
)
