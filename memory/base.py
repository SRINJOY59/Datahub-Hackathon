"""Memory subsystem — the pluggable 'place' for incident knowledge.

`MemoryStore` is the interface (also declared in agent.contracts). Backends:

  * DataHubMemory  (default) — post-mortems written back onto the asset in the
    graph; recall queries the graph. This is the moat: the context graph gets
    smarter with every incident, and any other agent/human inherits it.
  * VectorMemory   (roadmap) — embeddings for semantic recall of similar incidents.
  * CodebaseMemory (roadmap) — indexes repo transforms + dependency manifests to
    link code/dependency changes to downstream ML impact.

Select a backend via get_memory(); swap the default without touching the core.
"""
from __future__ import annotations

import os

from agent.contracts import MemoryStore


def get_memory(kind: str | None = None,
               gms_server: str = "http://localhost:8080") -> MemoryStore:
    kind = kind or os.getenv("SENTINEL_MEMORY", "datahub")
    if kind == "datahub":
        from memory.datahub_memory import DataHubMemory

        return DataHubMemory(gms_server)
    raise ValueError(f"unknown memory backend: {kind}")
