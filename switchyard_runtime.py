from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import switchyard_runtime_impl as _impl
from switchyard_runtime_impl import *
from switchyard_persistence import RecoveryNotice, resilient_load_json, resilient_save_json

_RUNTIME_RECOVERY_NOTICE: RecoveryNotice | None = None


def _decode_runtime(data: dict) -> RuntimeSettings:
    def rows(key: str) -> list[dict]:
        value = data.get(key, [])
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError(f'{key} must be a list of objects')
        return value

    session_profiles = data.get('session_profiles') or {}
    if not isinstance(session_profiles, dict):
        raise ValueError('session_profiles must be an object')
    last_session_id = data.get('last_session_id')
    if last_session_id is not None and not isinstance(last_session_id, str):
        raise ValueError('last_session_id must be a string or null')
    return _impl.RuntimeSettings(
        profiles=[_impl._profile_from_dict(item) for item in rows('profiles')],
        policies=[_impl._policy_from_dict(item) for item in rows('policies')],
        session_profiles={str(k): str(v) for k, v in session_profiles.items()},
        last_session_id=last_session_id,
        version=RUNTIME_VERSION,
    )


def _validate_runtime(data: dict) -> None:
    _decode_runtime(data)


def load_runtime(path: Path = RUNTIME_FILE) -> RuntimeSettings:
    global _RUNTIME_RECOVERY_NOTICE
    data, notice = resilient_load_json(Path(path), RUNTIME_VERSION, label='Runtime settings', validator=_validate_runtime)
    _RUNTIME_RECOVERY_NOTICE = notice
    if data is None:
        return RuntimeSettings()
    try:
        return _decode_runtime(data)
    except Exception as exc:
        _RUNTIME_RECOVERY_NOTICE = RecoveryNotice('Runtime settings', f'Runtime settings could not be decoded; starting with safe defaults. {exc}')
        return RuntimeSettings()


def save_runtime(settings: RuntimeSettings, path: Path = RUNTIME_FILE) -> None:
    settings.version = RUNTIME_VERSION
    resilient_save_json(Path(path), asdict(settings), RUNTIME_VERSION, validator=_validate_runtime)


def runtime_recovery_notice(clear: bool = False) -> RecoveryNotice | None:
    global _RUNTIME_RECOVERY_NOTICE
    notice = _RUNTIME_RECOVERY_NOTICE
    if clear:
        _RUNTIME_RECOVERY_NOTICE = None
    return notice
