from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import switchyard_core_impl as _impl
from switchyard_core_impl import *
from switchyard_persistence import RecoveryNotice, resilient_load_json, resilient_save_json

_STATE_RECOVERY_NOTICE: RecoveryNotice | None = None


def _require_string_list(value, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f'{label} must be a list of strings')


def _require_object_list(value, label: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f'{label} must be a list of objects')
    return value


def _require_mapping(value, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be an object')


def _validate_nested_state(data: dict) -> None:
    for project in _require_object_list(data.get('projects', []), 'projects'):
        if not isinstance(project.get('name'), str) or not isinstance(project.get('path'), str):
            raise ValueError('project name and path must be strings')
        _require_string_list(project.get('tags', []), 'project.tags')
        for config in _require_object_list(project.get('run_configs', []), 'project.run_configs'):
            if not isinstance(config.get('name'), str) or not isinstance(config.get('command'), str):
                raise ValueError('run configuration name and command must be strings')
            _require_mapping(config.get('env', {}), 'run configuration env')

    for service in _require_object_list(data.get('services', []), 'services'):
        _require_string_list(service.get('depends_on', []), 'service.depends_on')
        _require_mapping(service.get('env', {}), 'service.env')
        readiness = service.get('readiness')
        if readiness is not None and not isinstance(readiness, dict):
            raise ValueError('service.readiness must be an object or null')

    for session in _require_object_list(data.get('sessions', []), 'sessions'):
        _require_string_list(session.get('service_ids', []), 'session.service_ids')

    _require_object_list(data.get('run_history', []), 'run_history')
    _require_object_list(data.get('session_history', []), 'session_history')


def _decode_state(data: dict) -> WorkspaceState:
    _validate_nested_state(data)

    def rows(key: str) -> list[dict]:
        return _require_object_list(data.get(key, []), key)

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
