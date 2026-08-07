"""Plugin registries for the investigation platform.

Detectors, Probes, Actuators and CheckRunners self-register via decorators. The
core builds them on demand — so adding a new incident class is a matter of
dropping a new module in agent/tools/<kind>/ and decorating the class. Nothing
in the core needs to change.

Construction convention: a plugin may declare `gms_server` in its __init__ if it
talks to DataHub, or omit it entirely. We inspect the signature to decide, rather
than calling and catching TypeError — a TypeError raised *inside* a constructor
body would otherwise be mistaken for "this class takes no gms_server" and the
plugin would be silently rebuilt in a half-configured state.
"""
from __future__ import annotations

import inspect
from typing import TypeVar

from agent.contracts import ActionType

T = TypeVar("T")

DEFAULT_GMS = "http://localhost:8080"

_DETECTORS: list[type] = []
_PROBES: list[type] = []
_ACTUATORS: list[type] = []
_CHECKS: list[type] = []


def detector(cls: T) -> T:
    _DETECTORS.append(cls)
    return cls


def probe(cls: T) -> T:
    _PROBES.append(cls)
    return cls


def actuator(cls: T) -> T:
    _ACTUATORS.append(cls)
    return cls


def check(cls: T) -> T:
    _CHECKS.append(cls)
    return cls


def _accepts_gms(cls: type) -> bool:
    try:
        params = inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):  # C-level or unintrospectable __init__
        return False
    if "gms_server" in params:
        return True
    # a **kwargs-style constructor can absorb it
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _build(classes: list[type], gms_server: str) -> list:
    """Instantiate every registered class. A plugin whose constructor raises is
    skipped rather than sinking the whole registry — one broken plugin must not
    take the agent down. It is reported, though: a silently-empty registry is
    indistinguishable from a healthy pipeline, which is the failure mode we most
    need to avoid."""
    built = []
    for cls in classes:
        try:
            built.append(cls(gms_server=gms_server) if _accepts_gms(cls) else cls())
        except Exception as e:
            print(f"  [registry ] skipped {cls.__name__}: {type(e).__name__}: {e}")
    return built


def build_detectors(gms_server: str = DEFAULT_GMS) -> list:
    return _build(_DETECTORS, gms_server)


def build_probes(gms_server: str = DEFAULT_GMS) -> list:
    return _build(_PROBES, gms_server)


def build_checks(gms_server: str = DEFAULT_GMS) -> list:
    """Checks are filtered per-asset by applies_to(), so a list is the right shape."""
    return _build(_CHECKS, gms_server)


def build_actuators(gms_server: str = DEFAULT_GMS) -> dict[ActionType, object]:
    """Actuators are dispatched by ActionType, so they come back as a mapping.
    A later registration for the same ActionType wins, which is what lets a
    deployment override a built-in actuator with its own."""
    return {a.action_type: a for a in _build(_ACTUATORS, gms_server)}
