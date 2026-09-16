from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from switchyard_core import (
    ManagedProcess,
    ReadinessCheck,
    RunConfig,
    Service,
    SessionController,
    SessionEvent,
    STATE_DIR,
    WorkspaceSession,
    WorkspaceState,
    check_port,
    command_available,
    readiness_description,
    service_dependents,
    service_project,
    topological_service_order,
    validate_service_graph,
    wait_for_readiness,
)

RUNTIME_FILE = STATE_DIR / 'runtime.json'
RUNTIME_VERSION = 1


@dataclass
class EnvironmentProfile:
    id: str
    name: str
    variables: dict[str, str] = field(default_factory=dict)
    inherit_keys: list[str] = field(default_factory=list)


@dataclass
class ServiceRuntimePolicy:
    service_id: str
    restart: str = 'never'  # never | on_failure | always
    max_restarts: int = 3
    base_backoff: float = 1.0
    max_backoff: float = 8.0
    profile_id: str | None = None


@dataclass
class RuntimeSettings:
    profiles: list[EnvironmentProfile] = field(default_factory=list)
    policies: list[ServiceRuntimePolicy] = field(default_factory=list)
    session_profiles: dict[str, str] = field(default_factory=dict)
    last_session_id: str | None = None
    version: int = RUNTIME_VERSION


@dataclass
class PreflightCheck:
    level: str  # PASS | WARN | ERROR
    name: str
    detail: str
    service_id: str | None = None


def _profile_from_dict(data: dict) -> EnvironmentProfile:
    return EnvironmentProfile(
        id=data.get('id') or uuid.uuid4().hex,
        name=data.get('name', 'Environment'),
        variables={str(k): str(v) for k, v in (data.get('variables') or {}).items()},
        inherit_keys=[str(x) for x in (data.get('inherit_keys') or [])],
    )


def _policy_from_dict(data: dict) -> ServiceRuntimePolicy:
    return ServiceRuntimePolicy(
        service_id=data.get('service_id', ''),
        restart=data.get('restart', 'never'),
        max_restarts=max(0, int(data.get('max_restarts', 3))),
        base_backoff=max(0.0, float(data.get('base_backoff', 1.0))),
        max_backoff=max(0.0, float(data.get('max_backoff', 8.0))),
        profile_id=data.get('profile_id'),
    )


def load_runtime(path: Path = RUNTIME_FILE) -> RuntimeSettings:
    if not path.exists():
        return RuntimeSettings()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return RuntimeSettings()
    return RuntimeSettings(
        profiles=[_profile_from_dict(x) for x in data.get('profiles', [])],
        policies=[_policy_from_dict(x) for x in data.get('policies', [])],
        session_profiles={str(k): str(v) for k, v in (data.get('session_profiles') or {}).items()},
        last_session_id=data.get('last_session_id'),
        version=RUNTIME_VERSION,
    )


def save_runtime(settings: RuntimeSettings, path: Path = RUNTIME_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    settings.version = RUNTIME_VERSION
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(asdict(settings), indent=2), encoding='utf-8')
    temp.replace(path)


def new_profile(name: str) -> EnvironmentProfile:
    return EnvironmentProfile(uuid.uuid4().hex, name)


def policy_for(settings: RuntimeSettings, service_id: str) -> ServiceRuntimePolicy:
    policy = next((p for p in settings.policies if p.service_id == service_id), None)
    if policy is None:
        policy = ServiceRuntimePolicy(service_id)
        settings.policies.append(policy)
    return policy


def profile_by_id(settings: RuntimeSettings, profile_id: str | None) -> EnvironmentProfile | None:
    if not profile_id:
        return None
    return next((p for p in settings.profiles if p.id == profile_id), None)


def profile_for_service(settings: RuntimeSettings, session: WorkspaceSession, service_id: str) -> EnvironmentProfile | None:
    policy = next((p for p in settings.policies if p.service_id == service_id), None)
    profile_id = policy.profile_id if policy and policy.profile_id else settings.session_profiles.get(session.id)
    return profile_by_id(settings, profile_id)


def resolve_profile(profile: EnvironmentProfile | None, source_env: dict[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    if profile is None:
        return {}, []
    source = os.environ if source_env is None else source_env
    resolved = dict(profile.variables)
    missing: list[str] = []
    for key in profile.inherit_keys:
        if key in source:
            resolved[key] = source[key]
        else:
            missing.append(key)
    return resolved, missing


def masked_profile_rows(profile: EnvironmentProfile) -> list[tuple[str, str, str]]:
    rows = [(key, value, 'stored') for key, value in sorted(profile.variables.items())]
    rows.extend((key, '••••••••', 'inherited') for key in sorted(profile.inherit_keys))
    return rows


def http_probe(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return False, 'invalid HTTP URL'
    request = urllib.request.Request(url, headers={'User-Agent': 'Switchyard/1'}, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=max(.1, timeout)) as response:
            status = int(getattr(response, 'status', 200))
            return (200 <= status < 400), f'HTTP {status}'
    except urllib.error.HTTPError as exc:
        return False, f'HTTP {exc.code}'
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, 'reason', exc)
        return False, str(reason)


def wait_for_runtime_readiness(service: Service, managed: ManagedProcess, poll: float = .1, cancel: threading.Event | None = None) -> tuple[bool, str]:
    if service.readiness.kind != 'http':
        return wait_for_readiness(service, managed, poll=poll, cancel=cancel)
    deadline = time.time() + max(0.1, service.readiness.timeout)
    while True:
        if cancel and cancel.is_set():
            return False, 'cancelled'
        if not managed.running:
            return False, f'exited {managed.returncode}'
        ok, detail = http_probe(service.readiness.target, timeout=min(1.0, max(.1, deadline - time.time())))
        if ok:
            return True, detail
        if time.time() >= deadline:
            return False, f'timed out waiting for {service.readiness.target} ({detail})'
        time.sleep(poll)


def runtime_readiness_description(check: ReadinessCheck) -> str:
    if check.kind == 'http':
        return f'HTTP {check.target}'
    return readiness_description(check)


def session_preflight(state: WorkspaceState, session: WorkspaceSession, settings: RuntimeSettings) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    graph_errors = validate_service_graph(state.services)
    try:
        services = topological_service_order(state.services, session.service_ids)
    except ValueError as exc:
        services = []
        graph_errors.append(str(exc))
    if graph_errors:
        for error in dict.fromkeys(graph_errors):
            checks.append(PreflightCheck('ERROR', 'Service graph', error))
        return checks
    checks.append(PreflightCheck('PASS', 'Service graph', f'{len(services)} service(s) in valid dependency order'))

    claimed_ports: dict[tuple[str, str], str] = {}
    for service in services:
        project = service_project(service, state)
        if not project or not Path(project.path).is_dir():
            checks.append(PreflightCheck('ERROR', 'Project', f'{service.name}: project folder is unavailable', service.id))
        else:
            checks.append(PreflightCheck('PASS', 'Project', f'{service.name}: {project.name}', service.id))
        if not command_available(service.command):
            checks.append(PreflightCheck('WARN', 'Command', f'{service.name}: executable could not be resolved on PATH', service.id))
        profile = profile_for_service(settings, session, service.id)
        _, missing = resolve_profile(profile)
        if missing:
            checks.append(PreflightCheck('ERROR', 'Environment', f'{service.name}: missing inherited variable(s): {", ".join(missing)}', service.id))
        elif profile:
            checks.append(PreflightCheck('PASS', 'Environment', f'{service.name}: profile {profile.name}', service.id))

        readiness = service.readiness
        if readiness.kind == 'port':
            try:
                port = int(readiness.target)
            except (TypeError, ValueError):
                checks.append(PreflightCheck('ERROR', 'Readiness', f'{service.name}: invalid port {readiness.target!r}', service.id)); continue
            key = (readiness.host, str(port))
            if key in claimed_ports:
                checks.append(PreflightCheck('ERROR', 'Port conflict', f'{service.name} and {claimed_ports[key]} both claim {readiness.host}:{port}', service.id))
            else:
                claimed_ports[key] = service.name
            if check_port(readiness.host, port):
                checks.append(PreflightCheck('WARN', 'Port already open', f'{readiness.host}:{port} is listening before session start', service.id))
        elif readiness.kind == 'http':
            parsed = urllib.parse.urlparse(readiness.target)
            if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                checks.append(PreflightCheck('ERROR', 'Readiness', f'{service.name}: invalid HTTP readiness URL', service.id))
        elif readiness.kind == 'delay':
            try:
                float(readiness.target or 0)
            except ValueError:
                checks.append(PreflightCheck('ERROR', 'Readiness', f'{service.name}: invalid readiness delay', service.id))
        elif readiness.kind != 'process':
            checks.append(PreflightCheck('ERROR', 'Readiness', f'{service.name}: unsupported readiness kind {readiness.kind}', service.id))
    if not any(c.level == 'ERROR' for c in checks):
        checks.append(PreflightCheck('PASS', 'Preflight', 'No blocking startup problems found'))
    return checks


def preflight_ok(checks: Iterable[PreflightCheck]) -> bool:
    return not any(check.level == 'ERROR' for check in checks)


class ResilientSessionController(SessionController):
    """Phase 4 controller: profile-aware, parallel by dependency layer, and restart-capable."""

    def __init__(
        self,
        state: WorkspaceState,
        session: WorkspaceSession,
        runtime: RuntimeSettings,
        on_event: Callable[[SessionEvent], None] | None = None,
        on_line: Callable[[Service, str], None] | None = None,
    ):
        super().__init__(state, session, on_event=on_event, on_line=on_line)
        self.runtime = runtime
        self.restart_counts: dict[str, int] = {}
        self._restarting: set[str] = set()
        self._runtime_lock = threading.RLock()

    def _effective_env(self, service: Service) -> tuple[dict[str, str], list[str]]:
        profile = profile_for_service(self.runtime, self.session, service.id)
        values, missing = resolve_profile(profile)
        values.update(service.env)
        return values, missing

    def _start_one(self, service: Service) -> tuple[bool, str]:
        project = service_project(service, self.state)
        if not project or not Path(project.path).is_dir():
            return False, 'project is unavailable'
        env, missing = self._effective_env(service)
        if missing:
            return False, f'missing environment variable(s): {", ".join(missing)}'
        config = RunConfig(service.id, service.name, service.command, service.cwd, env)
        managed = ManagedProcess(config, project)
        with self._runtime_lock:
            self.processes[service.id] = managed
        try:
            pid = managed.start(
                lambda line, s=service: self.on_line(s, line) if self.on_line else None,
                lambda rc, s=service: self._process_exit(s, rc),
            )
        except Exception as exc:
            return False, str(exc)
        self._emit('service-start', f'{service.name} started · pid {pid}', service.id)
        ok, detail = wait_for_runtime_readiness(service, managed, cancel=self._cancel)
        if ok:
            with self._runtime_lock:
                self.ready.add(service.id)
                self.failed.discard(service.id)
            self._emit('ready', f'{service.name}: {detail}', service.id)
        return ok, detail

    def _start_worker(self) -> None:
        checks = session_preflight(self.state, self.session, self.runtime)
        blockers = [c for c in checks if c.level == 'ERROR']
        if blockers:
            self.status = 'FAILED'
            for check in blockers:
                self._emit('preflight-error', f'{check.name}: {check.detail}', check.service_id)
            return
        try:
            order = topological_service_order(self.state.services, self.session.service_ids)
        except ValueError as exc:
            self.status = 'FAILED'; self._emit('error', str(exc)); return
        selected = {s.id: s for s in order}
        pending = set(selected)
        self.runtime.last_session_id = self.session.id
        self._emit('session-start', f'Starting {self.session.name}')

        while pending and not self._cancel.is_set():
            blocked = [sid for sid in pending if any(dep in self.failed for dep in selected[sid].depends_on)]
            for sid in blocked:
                pending.remove(sid); self.failed.add(sid); self._emit('blocked', f'{selected[sid].name}: dependency failed', sid)
            candidates = [selected[sid] for sid in pending if all(dep in self.ready for dep in selected[sid].depends_on)]
            if not candidates:
                if pending:
                    for sid in list(pending):
                        self.failed.add(sid); self._emit('blocked', f'{selected[sid].name}: dependencies never became ready', sid); pending.remove(sid)
                break
            workers = min(4, len(candidates))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='switchyard-start') as pool:
                futures = {pool.submit(self._start_one, service): service for service in candidates}
                for future in as_completed(futures):
                    service = futures[future]
                    pending.discard(service.id)
                    try:
                        ok, detail = future.result()
                    except Exception as exc:
                        ok, detail = False, str(exc)
                    if not ok:
                        self.failed.add(service.id); self._emit('not-ready', f'{service.name}: {detail}', service.id)
                        proc = self.processes.get(service.id)
                        if proc and proc.running:
                            proc.stop()
        if self._cancel.is_set():
            self.status = 'STOPPED'
        elif self.failed:
            self.status = 'DEGRADED'
            self._emit('session-degraded', f'{self.session.name} started with {len(self.failed)} failed/blocked service(s)')
        else:
            self.status = 'RUNNING'
            self._emit('session-ready', f'{self.session.name} is ready')

    def _should_restart(self, service: Service, returncode: int) -> bool:
        policy = next((p for p in self.runtime.policies if p.service_id == service.id), ServiceRuntimePolicy(service.id))
        if policy.restart == 'always':
            return True
        if policy.restart == 'on_failure' and returncode != 0:
            return True
        return False

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
            self.status = 'DEGRADED'
            self._emit('restart-scheduled', f'{service.name}: restart {count + 1}/{policy.max_restarts} in {delay:g}s', service.id)
            threading.Thread(target=self._restart_worker, args=(service, delay), daemon=True).start()
            return
        if returncode != 0:
            self.failed.add(service.id)
            self._cascade_failure(service)

    def _restart_worker(self, service: Service, delay: float) -> None:
        if self._cancel.wait(delay):
            self._restarting.discard(service.id); return
        missing_deps = [dep for dep in service.depends_on if dep not in self.ready]
        if missing_deps:
            self.failed.add(service.id); self._restarting.discard(service.id)
            self._emit('restart-aborted', f'{service.name}: dependency is not ready', service.id)
            self._cascade_failure(service); return
        self._emit('restart', f'Restarting {service.name}', service.id)
        ok, detail = self._start_one(service)
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
        if count < policy.max_restarts and not self._cancel.is_set():
            self._restarting.add(service.id)
            self.restart_counts[service.id] = count + 1
            next_delay = min(policy.max_backoff, policy.base_backoff * (2 ** count))
            threading.Thread(target=self._restart_worker, args=(service, next_delay), daemon=True).start()
        else:
            self._cascade_failure(service)

    def _cascade_failure(self, service: Service) -> None:
        if service.failure_policy != 'stop_dependents':
            self.status = 'DEGRADED'; return
        for dependent in service_dependents(self.state.services, service.id):
            proc = self.processes.get(dependent.id)
            if proc and proc.running:
                proc.stop(); self.ready.discard(dependent.id)
                self._emit('cascade-stop', f'{dependent.name} stopped because {service.name} failed', dependent.id)
        self.status = 'DEGRADED'
