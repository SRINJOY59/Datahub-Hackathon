"""Console setup.

On Windows, Python picks the legacy cp1252 code page for stdout whenever output
is redirected — piped into a file, a grep, or a CI log. Any character outside
that set then raises UnicodeEncodeError, so a run that works in the terminal dies
the moment someone pipes it somewhere. The agent's output is full of arrows,
dashes and deltas, so this is not hypothetical.

Forcing UTF-8 at the entry points fixes the whole class of problem in one place,
rather than avoiding punctuation forever.
"""
from __future__ import annotations

import sys


def enable_utf8() -> None:
    """Make stdout/stderr accept the characters we actually print. Falls back to
    replacement characters rather than failing, because losing a dash is always
    better than losing the run."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            continue
