from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import switchyard_core_impl as _impl
from switchyard_core_impl import *
from switchyard_persistence import RecoveryNotice, resilient_load_json, resilient_save_json

_STATE_RECOVERY_NOTICE: RecoveryNotice | None = None


def _decode_state(data: dict) -> WorkspaceState:
    def rows(key: str) -> list[dict]:
        value = data.get(key, [])
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError(f'{key} must be a list of objects')
        return value

    selected = data.get('selected_project')
    if selected is not None and not isinstance(selected, str):
        raise ValueError('selected_project must be a string or null')
    return _impl.WorkspaceState(
        projects=[_impl._project_from_dict(item) for item in rows('projects')],
        selected_project=selected,
        run_history=[_impl._record_from_dict(item) for item in rows('run_history')],
        services=[_impl._service_from_dict(item) for item in rows('services')],
        sessions=[_impl._session_from_dict(item) for item in rows('sessions')],
        session_history=[_impl._event_from_dict(item) for item in rows('session_history')],
        version=STATE_VERSION,
    )


def _validate_state(data: dict) -> None:
    _decode_state(data)


def load_state(path: Path = STATE_FILE) -> WorkspaceState:
    global _STATE_RECOVERY_NOTICE
    data, notice = resilient_load_json(Path(path), STATE_VERSION, label='Workspace state', validator=_validate_state)
    _STATE_RECOVERY_NOTICE = notice
    if data is None:
        return WorkspaceState()
    try:
        return _decode_state(data)
    except Exception as exc:
        _STATE_RECOVERY_NOTICE = RecoveryNotice('Workspace state', f'Workspace state could not be decoded; starting with safe defaults. {exc}')
        return WorkspaceState()


def save_state(state: WorkspaceState, path: Path = STATE_FILE) -> None:
    state.version = STATE_VERSION
    state.run_history[:] = state.run_history[-250:]
    state.session_history[:] = state.session_history[-500:]
    resilient_save_json(Path(path), asdict(state), STATE_VERSION, validator=_validate_state)


def state_recovery_notice(clear: bool = False) -> RecoveryNotice | None:
    global _STATE_RECOVERY_NOTICE
    notice = _STATE_RECOVERY_NOTICE
    if clear:
        _STATE_RECOVERY_NOTICE = None
    return notice
