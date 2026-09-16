from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

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


# The implementation's recovery helpers resolve pid_alive from their own module
# globals. Patch that reference once so callers of recovery_processes() and
# terminate_pid_tree() also use the non-signalling Windows implementation.
_impl.pid_alive = pid_alive
