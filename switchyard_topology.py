from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path

import switchyard_topology_impl as _impl
from switchyard_topology_impl import *


def pid_alive(pid: int) -> bool:
    """Cross-platform liveness check that never signals the target on Windows."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok and code.value == STILL_ACTIVE)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError):
        return False


def _meaningful_recovery(marker: dict | None) -> bool:
    return bool(marker and (marker.get('active_session_id') or marker.get('processes')))


def begin_recovery_journal(path: Path = RECOVERY_FILE) -> dict | None:
    """Arm recovery for this run without discarding an unresolved prior crash.

    The original Phase 5 journal overwrote the previous marker immediately. If
    Switchyard crashed a second time before the user handled the recovery dialog,
    the first run's orphan PIDs were lost. Carry the unresolved marker inside the
    new journal so another startup can still surface it.
    """
    previous = _impl.recovery_marker(path)
    pending = None
    if _meaningful_recovery(previous):
        pending = dict(previous)
    elif isinstance(previous, dict) and _meaningful_recovery(previous.get('pending_recovery')):
        pending = dict(previous['pending_recovery'])

    path.parent.mkdir(parents=True, exist_ok=True)
    current = {
        'version': 3,
        'pid': os.getpid(),
        'started_at': time.time(),
        'active_session_id': None,
        'active_session_name': None,
        'processes': {},
        'pending_recovery': pending,
    }
    _impl._atomic_json(path, current)
    return pending


def acknowledge_recovery_journal(path: Path = RECOVERY_FILE) -> None:
    """Forget a previously offered recovery while keeping this run armed."""
    data = _impl.recovery_marker(path)
    if not data:
        return
    data['pending_recovery'] = None
    data['updated_at'] = time.time()
    _impl._atomic_json(path, data)


def clean_recovery_journal(path: Path = RECOVERY_FILE) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# The implementation's recovery helpers resolve pid_alive and journal helpers
# from their own module globals. Patch the liveness reference so callers of
# recovery_processes() and terminate_pid_tree() use the non-signalling Windows
# implementation. update_recovery_journal intentionally preserves unknown keys,
# including pending_recovery, when it rewrites the armed marker.
_impl.pid_alive = pid_alive
