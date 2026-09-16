from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import threading

import switchyard_runtime_impl as _impl
from switchyard_runtime_impl import *
from switchyard_persistence import RecoveryNotice, resilient_load_json, resilient_save_json

_RUNTIME_RECOVERY_NOTICE: RecoveryNotice | None = None
_BASE_SESSION_PREFLIGHT = _impl.session_preflight


def _string_list(value, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f'{label} must be a list of strings')
    return list(value)


def _decode_runtime(data: dict) -> RuntimeSettings:
    def rows(key: str) -> list[dict]:
        value = data.get(key, [])
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError(f'{key} must be a list of objects')
        return value

    def profile(item: dict) -> EnvironmentProfile:
        variables = item.get('variables') or {}
        if not isinstance(variables, dict):
            raise ValueError('profile.variables must be an object')
        inherit_keys = _string_list(item.get('inherit_keys'), 'profile.inherit_keys')
        return EnvironmentProfile(
            id=item.get('id') or _impl.uuid.uuid4().hex,
            name=str(item.get('name', 'Environment')),
            variables={str(k): str(v) for k, v in variables.items()},
            inherit_keys=inherit_keys,
        )

    def policy(item: dict) -> ServiceRuntimePolicy:
        service_id = item.get('service_id', '')
        restart = item.get('restart', 'never')
        if not isinstance(service_id, str):
            raise ValueError('policy.service_id must be a string')
        if restart not in {'never', 'on_failure', 'always'}:
            raise ValueError('policy.restart must be never, on_failure, or always')
        profile_id = item.get('profile_id')
        if profile_id is not None and not isinstance(profile_id, str):
            raise ValueError('policy.profile_id must be a string or null')
        try:
            max_restarts = max(0, int(item.get('max_restarts', 3)))
            base_backoff = max(0.0, float(item.get('base_backoff', 1.0)))
            max_backoff = max(0.0, float(item.get('max_backoff', 8.0)))
        except (TypeError, ValueError) as exc:
            raise ValueError('policy restart limits/backoff must be numeric') from exc
        return ServiceRuntimePolicy(service_id, restart, max_restarts, base_backoff, max_backoff, profile_id)

    session_profiles = data.get('session_profiles') or {}
    if not isinstance(session_profiles, dict):
        raise ValueError('session_profiles must be an object')
    last_session_id = data.get('last_session_id')
    if last_session_id is not None and not isinstance(last_session_id, str):
        raise ValueError('last_session_id must be a string or null')
    return _impl.RuntimeSettings(
        profiles=[profile(item) for item in rows('profiles')],
        policies=[policy(item) for item in rows('policies')],
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


def session_preflight(state: WorkspaceState, session: WorkspaceSession, settings: RuntimeSettings) -> list[PreflightCheck]:
    """V1 fail-closed preflight.

    A readiness port that is already occupied before launch cannot safely prove that
    the managed service became ready, so V1 treats it as a blocker instead of a
    warning. This prevents an unrelated listener from producing a false READY state.
    """
    checks = _BASE_SESSION_PREFLIGHT(state, session, settings)
    hardened: list[PreflightCheck] = []
    for check in checks:
        if check.name == 'Port already open' and check.level == 'WARN':
            hardened.append(PreflightCheck('ERROR', check.name, check.detail, check.service_id))
        else:
            hardened.append(check)
    return hardened


# The implementation's startup worker resolves its preflight function from its own
# module globals. Point that reference at the hardened wrapper so every controller,
# including inherited worker code, uses the same fail-closed policy.
_impl.session_preflight = session_preflight


class ResilientSessionController(_impl.ResilientSessionController):
    """V1 lifecycle-hardened runtime controller.

    Each user-initiated start gets a generation token. Restart workers from a prior
    run are therefore unable to wake up after a stop/start cycle and launch stale
    duplicate processes. Restart budgets also reset for each new user start.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._run_generation = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError('Session is already starting')
        if self.running:
            raise RuntimeError('Session already has running services')
        with self._runtime_lock:
            self._run_generation += 1
            self.restart_counts.clear()
            self._restarting.clear()
        super().start()

    def stop(self) -> None:
        # Arm cancellation before invalidating restart workers so a process exit that
        # races with Stop is always treated as intentional.
        self._cancel.set()
        with self._runtime_lock:
            self._run_generation += 1
            self._restarting.clear()
        super().stop()
        worker = self._thread
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=2.0)

    def _process_exit(self, service: Service, returncode: int) -> None:
        self.ready.discard(service.id)
        self._emit('service-exit', f'{service.name} exited {returncode}', service.id)
        if self._cancel.is_set() or service.id in self._restarting:
            return
        policy = next((p for p in self.runtime.policies if p.service_id == service.id), ServiceRuntimePolicy(service.id))
        count = self.restart_counts.get(service.id, 0)
        if self._should_restart(service, returncode) and count < policy.max_restarts:
            self.restart_counts[service.id] = count + 1
            self._restarting.add(service.id)
            delay = min(policy.max_backoff, policy.base_backoff * (2 ** count))
            generation = self._run_generation
            self.status = 'DEGRADED'
            self._emit('restart-scheduled', f'{service.name}: restart {count + 1}/{policy.max_restarts} in {delay:g}s', service.id)
            threading.Thread(target=self._restart_worker, args=(service, delay, generation), daemon=True).start()
            return
        if returncode != 0:
            self.failed.add(service.id)
            self._cascade_failure(service)

    def _restart_worker(self, service: Service, delay: float, generation: int | None = None) -> None:
        generation = self._run_generation if generation is None else generation
        if generation != self._run_generation:
            return
        if self._cancel.wait(delay):
            if generation == self._run_generation:
                self._restarting.discard(service.id)
            return
        if generation != self._run_generation:
            return
        missing_deps = [dep for dep in service.depends_on if dep not in self.ready]
        if missing_deps:
            self.failed.add(service.id)
            self._restarting.discard(service.id)
            self._emit('restart-aborted', f'{service.name}: dependency is not ready', service.id)
            self._cascade_failure(service)
            return
        self._emit('restart', f'Restarting {service.name}', service.id)
        ok, detail = self._start_one(service)
        if generation != self._run_generation:
            proc = self.processes.get(service.id)
            if proc and proc.running:
                proc.stop()
            return
        self._restarting.discard(service.id)
        if ok:
            self._emit('restart-ready', f'{service.name}: {detail}', service.id)
            if not self.failed and not self._restarting:
                self.status = 'RUNNING'
            return
        self._emit('restart-failed', f'{service.name}: {detail}', service.id)
        self.failed.add(service.id)
        policy = next((p for p in self.runtime.policies if p.service_id == service.id), ServiceRuntimePolicy(service.id))
        count = self.restart_counts.get(service.id, 0)
        if count < policy.max_restarts and not self._cancel.is_set() and generation == self._run_generation:
            self._restarting.add(service.id)
            self.restart_counts[service.id] = count + 1
            next_delay = min(policy.max_backoff, policy.base_backoff * (2 ** count))
            threading.Thread(target=self._restart_worker, args=(service, next_delay, generation), daemon=True).start()
        else:
            self._cascade_failure(service)
