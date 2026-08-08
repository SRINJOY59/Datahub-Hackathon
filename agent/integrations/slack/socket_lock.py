"""Exactly one process may hold the Slack Socket Mode connection.

Slack does not broadcast an interaction to every open Socket Mode connection for
an app — it delivers each click to exactly one of them. So two Sentinel
processes connected at once (say `python -m agent serve` alongside a manual
`python -m agent`) silently steal each other's approvals: the click lands on
whichever process Slack picked, and the one actually blocked on the decision
waits out its full timeout.

A pid lockfile makes that impossible rather than merely discouraged. The first
process to start claims the socket; later ones skip it and fall back to the
approval policy in config/slack.yaml, which returns immediately instead of
hanging. A lock left behind by a killed process is reclaimed automatically.

Set SENTINEL_SLACK_SOCKET=0 to make a process decline the socket on purpose —
useful when you want a long-running `serve` to stay up but a manual run to own
interactive approvals.
"""
from __future__ import annotations

import atexit
import os
from pathlib import Path
from typing import Optional

_LOCK_PATH = Path(".sentinel/slack_socket.lock")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # A null handle is ambiguous: the process may simply be one we are not
        # allowed to open (elevated, or another user's). Only ERROR_INVALID_
        # PARAMETER actually means "no such pid" — treating access-denied as
        # dead would let us steal a lock a live process still holds.
        return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def current_owner() -> Optional[int]:
    """The pid holding the socket, or None if unheld."""
    try:
        return int(_LOCK_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def acquire() -> bool:
    """Claim the Socket Mode connection for this process."""
    if os.getenv("SENTINEL_SLACK_SOCKET", "1") == "0":
        return False

    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Two attempts: the second only runs after clearing a stale lock.
    for _ in range(2):
        try:
            fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            owner = current_owner()
            if owner is not None and owner != os.getpid() and _pid_alive(owner):
                return False
            try:
                _LOCK_PATH.unlink()
            except OSError:
                return False
            continue

        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        atexit.register(release)
        return True

    return False


def release() -> None:
    """Drop the lock, but only if this process is the one holding it."""
    if current_owner() == os.getpid():
        try:
            _LOCK_PATH.unlink()
        except OSError:
            pass
