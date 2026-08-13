"""Single source of truth for the DataHub GMS address.

Every component that talks to the graph used to carry its own
`gms_server: str = "http://localhost:8080"` default. That is correct on a
laptop and wrong everywhere else: any call site that forgot to thread the
configured URL through silently pointed at localhost, and in a container
localhost is the container itself. The failure is quiet in the worst way --
the component appears to work, then refuses connections against an address
nobody meant to use.

Defaults route through here instead, so an unset environment still means
localhost, but a configured DATAHUB_GMS_URL is picked up whether or not the
caller remembered to pass it.
"""
from __future__ import annotations

import os

#: Where DataHub runs when nothing says otherwise (a local quickstart).
LOCAL_GMS = "http://localhost:8080"


def default_gms_server() -> str:
    """The configured GMS address, falling back to a local quickstart.

    Read at call time rather than import time so that tests and the CLI can
    set DATAHUB_GMS_URL after the module graph is already loaded.
    """
    return os.environ.get("DATAHUB_GMS_URL", "").strip() or LOCAL_GMS
