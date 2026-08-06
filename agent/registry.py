"""Plugin registries for the investigation platform.

Detectors and Probes self-register via decorators. The RCA core builds them on
demand — so adding a new incident class is a matter of dropping a new module in
agent/tools/detectors or agent/tools/probes and decorating the class. Nothing in
the core needs to change.
"""
from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")

_DETECTORS: list[type] = []
_PROBES: list[type] = []


def detector(cls: T) -> T:
    _DETECTORS.append(cls)
    return cls


def probe(cls: T) -> T:
    _PROBES.append(cls)
    return cls


def _build(classes: list[type], gms_server: str) -> list:
    built = []
    for cls in classes:
        try:
            built.append(cls(gms_server=gms_server))
        except TypeError:
            built.append(cls())
    return built


def build_detectors(gms_server: str = "http://localhost:8080") -> list:
    return _build(_DETECTORS, gms_server)


def build_probes(gms_server: str = "http://localhost:8080") -> list:
    return _build(_PROBES, gms_server)
