from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, Callable
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid

STATE_DIR = Path.home() / '.switchyard'
STATE_FILE = STATE_DIR / 'state.json'
STATE_VERSION = 3
IGNORED_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build', '.next', 'target'}


@dataclass
class RunConfig:
    id: str
    name: str
    command: str
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    auto_restart: bool = False


@dataclass
class Project:
    id: str
    name: str
    path: str
    notes: str = ''
    run_configs: list[RunConfig] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    pinned: bool = False
    last_opened: float | None = None


@dataclass
class RunRecord:
    id: str
    project_id: str
    project_name: str
    config_id: str
    config_name: str
    command: str
    started_at: float
    ended_at: float | None = None
    returncode: int | None = None
    pid: int | None = None

    @property
    def duration(self) -> float | None:
        if self.ended_at is None:
            return None
        return max(0.0, self.ended_at - self.started_at)


@dataclass
class ReadinessCheck:
    kind: str = 'process'
    target: str = ''
    timeout: float = 30.0
    host: str = '127.0.0.1'


@dataclass
class Service:
    id: str
    project_id: str
    name: str
    command: str
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    readiness: ReadinessCheck = field(default_factory=ReadinessCheck)
    failure_policy: str = 'stop_dependents'


@dataclass
class WorkspaceSession:
    id: str
    name: str
    service_ids: list[str] = field(default_factory=list)
    stop_reverse_order: bool = True


@dataclass
class SessionEvent:
    timestamp: float
    session_id: str
    service_id: str | None
    kind: str
    message: str


@dataclass
class WorkspaceState:
    projects: list[Project] = field(default_factory=list)
    selected_project: str | None = None
    run_history: list[RunRecord] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
    sessions: list[WorkspaceSession] = field(default_factory=list)
    session_history: list[SessionEvent] = field(default_factory=list)
    version: int = STATE_VERSION


def _config_from_dict(d: dict) -> RunConfig:
    return RunConfig(
        id=d.get('id') or uuid.uuid4().hex,
        name=d['name'],
        command=d['command'],
        cwd=d.get('cwd'),
        env=dict(d.get('env') or {}),
        auto_restart=bool(d.get('auto_restart', False)),
    )


def _project_from_dict(d: dict) -> Project:
    return Project(
        id=d.get('id') or uuid.uuid4().hex,
        name=d['name'],
        path=d['path'],
        notes=d.get('notes', ''),
        run_configs=[_config_from_dict(x) for x in d.get('run_configs', [])],
        tags=list(d.get('tags') or []),
        pinned=bool(d.get('pinned', False)),
        last_opened=d.get('last_opened'),
    )


def _record_from_dict(d: dict) -> RunRecord:
    return RunRecord(
        id=d.get('id') or uuid.uuid4().hex,
        project_id=d.get('project_id', ''),
        project_name=d.get('project_name', ''),
        config_id=d.get('config_id', ''),
        config_name=d.get('config_name', ''),
        command=d.get('command', ''),
        started_at=float(d.get('started_at', 0)),
        ended_at=d.get('ended_at'),
        returncode=d.get('returncode'),
        pid=d.get('pid'),
    )


def _readiness_from_dict(d: dict | None) -> ReadinessCheck:
    d = d or {}
    return ReadinessCheck(
        kind=d.get('kind', 'process'),
        target=str(d.get('target', '')),
        timeout=float(d.get('timeout', 30.0)),
        host=d.get('host', '127.0.0.1'),
    )


def _service_from_dict(d: dict) -> Service:
    return Service(
        id=d.get('id') or uuid.uuid4().hex,
        project_id=d.get('project_id', ''),
        name=d.get('name', 'Service'),
        command=d.get('command', ''),
        cwd=d.get('cwd'),
        env=dict(d.get('env') or {}),
        depends_on=list(d.get('depends_on') or []),
        readiness=_readiness_from_dict(d.get('readiness')),
        failure_policy=d.get('failure_policy', 'stop_dependents'),
    )


def _session_from_dict(d: dict) -> WorkspaceSession:
    return WorkspaceSession(
        id=d.get('id') or uuid.uuid4().hex,
        name=d.get('name', 'Session'),
        service_ids=list(d.get('service_ids') or []),
        stop_reverse_order=bool(d.get('stop_reverse_order', True)),
    )


def _event_from_dict(d: dict) -> SessionEvent:
    return SessionEvent(
        timestamp=float(d.get('timestamp', 0)),
        session_id=d.get('session_id', ''),
        service_id=d.get('service_id'),
        kind=d.get('kind', 'info'),
        message=d.get('message', ''),
    )


def load_state(path: Path = STATE_FILE) -> WorkspaceState:
    if not path.exists():
        return WorkspaceState()
    data = json.loads(path.read_text(encoding='utf-8'))
    return WorkspaceState(
        projects=[_project_from_dict(x) for x in data.get('projects', [])],
        selected_project=data.get('selected_project'),
        run_history=[_record_from_dict(x) for x in data.get('run_history', [])],
        services=[_service_from_dict(x) for x in data.get('services', [])],
        sessions=[_session_from_dict(x) for x in data.get('sessions', [])],
        session_history=[_event_from_dict(x) for x in data.get('session_history', [])],
        version=STATE_VERSION,
    )


def save_state(state: WorkspaceState, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state.version = STATE_VERSION
    state.run_history[:] = state.run_history[-250:]
    state.session_history[:] = state.session_history[-500:]
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding='utf-8')
    tmp.replace(path)


def new_project(path: str | Path, name: str | None = None) -> Project:
    p = Path(path).expanduser().resolve()
    return Project(uuid.uuid4().hex, name or p.name, str(p), last_opened=time.time())


def new_service(project: Project, name: str, command: str, **kwargs) -> Service:
    return Service(uuid.uuid4().hex, project.id, name, command, **kwargs)


def new_session(name: str, service_ids: Iterable[str]) -> WorkspaceSession:
    return WorkspaceSession(uuid.uuid4().hex, name, list(service_ids))


def _git(project_path: Path, *args: str, timeout: float = 3.0) -> str:
    result = subprocess.run(
        ['git', '-C', str(project_path), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip() if result.returncode == 0 else ''


def git_snapshot(path: str | Path) -> dict:
    p = Path(path)
    out = {
        'git': False, 'branch': '', 'dirty': None, 'changed': 0,
        'upstream': '', 'ahead': 0, 'behind': 0, 'last_commit': '', 'remote': '',
    }
    if not p.is_dir() or not (p / '.git').exists():
        return out
    out['git'] = True
    try:
        out['branch'] = _git(p, 'branch', '--show-current')
        status = _git(p, 'status', '--porcelain')
        lines = [x for x in status.splitlines() if x.strip()]
        out['changed'] = len(lines)
        out['dirty'] = bool(lines)
        out['upstream'] = _git(p, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
        if out['upstream']:
            counts = _git(p, 'rev-list', '--left-right', '--count', f"{out['upstream']}...HEAD")
            parts = counts.replace('\t', ' ').split()
            if len(parts) == 2:
                out['behind'], out['ahead'] = int(parts[0]), int(parts[1])
        out['last_commit'] = _git(p, 'log', '-1', '--pretty=%h · %s · %cr')
        out['remote'] = _git(p, 'remote', 'get-url', 'origin')
    except Exception:
        pass
    return out


def project_snapshot(project: Project) -> dict:
    p = Path(project.path)
    out = {
        'exists': p.exists(), 'files': 0, 'bytes': 0,
        'run_configs': len(project.run_configs), 'modified': None,
    }
    out.update(git_snapshot(p))
    if not p.is_dir():
        return out
    newest = 0.0
    for base, dirs, files in os.walk(p):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for n in files:
            q = Path(base) / n
            try:
                st = q.stat()
                out['files'] += 1
                out['bytes'] += st.st_size
                newest = max(newest, st.st_mtime)
            except OSError:
                pass
    out['modified'] = newest or None
    return out


def _safe_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def detect_project(path: str | Path) -> dict:
    p = Path(path)
    stacks: list[str] = []
    evidence: list[str] = []
    tasks: list[dict[str, str]] = []
    ports: list[int] = []

    def add(stack: str, file_name: str) -> None:
        if stack not in stacks:
            stacks.append(stack)
        if file_name not in evidence:
            evidence.append(file_name)

    package = p / 'package.json'
    if package.exists():
        add('Node.js', 'package.json')
        data = _safe_json(package)
        deps = {**(data.get('dependencies') or {}), **(data.get('devDependencies') or {})}
        if '@tauri-apps/api' in deps or (p / 'src-tauri').exists():
            add('Tauri', 'src-tauri/')
        if 'react' in deps:
            add('React', 'react dependency')
        if 'next' in deps:
            add('Next.js', 'next dependency')
        scripts = data.get('scripts') or {}
        for key in ['dev', 'start', 'test', 'build', 'lint']:
            if key in scripts:
                tasks.append({'name': key.title(), 'command': f'npm run {key}', 'source': 'package.json'})
        if 'dev' in scripts:
            ports.extend([3000, 5173, 1420])

    if (p / 'pyproject.toml').exists() or (p / 'requirements.txt').exists() or any(p.glob('*.py')):
        add('Python', 'pyproject.toml' if (p / 'pyproject.toml').exists() else 'Python files')
        if (p / 'pytest.ini').exists() or (p / 'tests').exists():
            tasks.append({'name': 'Tests', 'command': 'python -m unittest discover -s tests -v', 'source': 'Python tests'})

    if (p / 'Cargo.toml').exists():
        add('Rust', 'Cargo.toml')
        tasks.extend([
            {'name': 'Cargo check', 'command': 'cargo check', 'source': 'Cargo.toml'},
            {'name': 'Cargo test', 'command': 'cargo test', 'source': 'Cargo.toml'},
        ])

    if (p / 'go.mod').exists():
        add('Go', 'go.mod')
        tasks.extend([
            {'name': 'Go test', 'command': 'go test ./...', 'source': 'go.mod'},
            {'name': 'Go run', 'command': 'go run .', 'source': 'go.mod'},
        ])

    if list(p.glob('*.sln')) or list(p.glob('*.csproj')):
        add('.NET', '.sln/.csproj')
        tasks.append({'name': 'dotnet build', 'command': 'dotnet build', 'source': '.NET project'})

    if (p / 'pom.xml').exists():
        add('Java/Maven', 'pom.xml')
        tasks.append({'name': 'Maven test', 'command': 'mvn test', 'source': 'pom.xml'})
    elif (p / 'build.gradle').exists() or (p / 'build.gradle.kts').exists():
        add('Java/Gradle', 'build.gradle')
        tasks.append({'name': 'Gradle test', 'command': 'gradle test', 'source': 'Gradle project'})

    if (p / 'Dockerfile').exists():
        add('Docker', 'Dockerfile')
    if (p / 'docker-compose.yml').exists() or (p / 'compose.yml').exists():
        add('Docker Compose', 'compose file')
        tasks.append({'name': 'Compose up', 'command': 'docker compose up', 'source': 'compose file'})

    seen_commands: set[str] = set()
    unique_tasks = []
    for task in tasks:
        if task['command'] not in seen_commands:
            seen_commands.add(task['command'])
            unique_tasks.append(task)

    return {
        'stacks': stacks,
        'evidence': evidence,
        'tasks': unique_tasks,
        'ports': sorted(set(ports)),
    }


def suggested_run_configs(project: Project) -> list[RunConfig]:
    detected = detect_project(project.path)
    existing = {c.command for c in project.run_configs}
    return [RunConfig(uuid.uuid4().hex, t['name'], t['command']) for t in detected['tasks'] if t['command'] not in existing]


def command_available(command: str) -> bool:
    first = command.strip().split()[0] if command.strip() else ''
    if not first:
        return False
    first = first.strip('"\'')
    return shutil.which(first) is not None


def check_port(host: str, port: int, timeout: float = .25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def scan_local_ports(ports: Iterable[int], host: str = '127.0.0.1') -> list[int]:
    return [p for p in ports if check_port(host, p)]


def project_health(project: Project) -> list[dict]:
    p = Path(project.path)
    checks = [{
        'name': 'Project folder', 'kind': 'path', 'target': project.path,
        'ok': p.is_dir(), 'detail': 'available' if p.is_dir() else 'missing',
    }]
    git = git_snapshot(p)
    if git['git']:
        checks.append({
            'name': 'Git working tree', 'kind': 'git', 'target': git['branch'] or 'repository',
            'ok': not bool(git['dirty']),
            'detail': 'clean' if not git['dirty'] else f"{git['changed']} changed file(s)",
        })
    for cfg in project.run_configs:
        available = command_available(cfg.command)
        checks.append({
            'name': f'Command · {cfg.name}', 'kind': 'command', 'target': cfg.command,
            'ok': available, 'detail': 'available' if available else 'executable not found on PATH',
        })
    detected = detect_project(p)
    for port in detected['ports']:
        open_ = check_port('127.0.0.1', port)
        checks.append({
            'name': f'Local port {port}', 'kind': 'port', 'target': str(port),
            'ok': open_, 'detail': 'listening' if open_ else 'not listening',
        })
    return checks


def service_project(service: Service, state: WorkspaceState) -> Project | None:
    return next((p for p in state.projects if p.id == service.project_id), None)


def validate_service_graph(services: Iterable[Service]) -> list[str]:
    services = list(services)
    ids = {s.id for s in services}
    errors: list[str] = []
    for service in services:
        for dep in service.depends_on:
            if dep == service.id:
                errors.append(f'{service.name} depends on itself')
            elif dep not in ids:
                errors.append(f'{service.name} references missing dependency {dep}')
    if errors:
        return errors
    try:
        topological_service_order(services)
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def topological_service_order(services: Iterable[Service], selected_ids: Iterable[str] | None = None) -> list[Service]:
    services = list(services)
    by_id = {s.id: s for s in services}
    if selected_ids is None:
        wanted = set(by_id)
    else:
        wanted = set(selected_ids)
        missing_selected = wanted - set(by_id)
        if missing_selected:
            raise ValueError(f'Missing service(s): {", ".join(sorted(missing_selected))}')
        stack = list(wanted)
        while stack:
            sid = stack.pop()
            for dep in by_id[sid].depends_on:
                if dep not in by_id:
                    raise ValueError(f'{by_id[sid].name} references missing dependency {dep}')
                if dep not in wanted:
                    wanted.add(dep)
                    stack.append(dep)

    result: list[Service] = []
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(service_id: str) -> None:
        if service_id in permanent:
            return
        if service_id in temporary:
            raise ValueError(f'Dependency cycle detected at {by_id[service_id].name}')
        temporary.add(service_id)
        service = by_id[service_id]
        for dep in service.depends_on:
            if dep not in by_id:
                raise ValueError(f'{service.name} references missing dependency {dep}')
            if dep in wanted:
                visit(dep)
        temporary.remove(service_id)
        permanent.add(service_id)
        if service_id in wanted:
            result.append(service)

    for service in services:
        if service.id in wanted:
            visit(service.id)
    return result


def service_dependents(services: Iterable[Service], service_id: str, transitive: bool = True) -> list[Service]:
    services = list(services)
    found: list[Service] = []
    seen: set[str] = set()
    queue = [service_id]
    while queue:
        current = queue.pop(0)
        for service in services:
            if service.id not in seen and current in service.depends_on:
                seen.add(service.id)
                found.append(service)
                if transitive:
                    queue.append(service.id)
    return found


def readiness_description(check: ReadinessCheck) -> str:
    if check.kind == 'port':
        return f'port {check.host}:{check.target}'
    if check.kind == 'delay':
        return f'delay {check.target or "0"}s'
    return 'process alive'


def wait_for_readiness(service: Service, managed: 'ManagedProcess', poll: float = .1, cancel: threading.Event | None = None) -> tuple[bool, str]:
    check = service.readiness
    deadline = time.time() + max(0.0, check.timeout)
    started = managed.started_at or time.time()
    while True:
        if cancel and cancel.is_set():
            return False, 'cancelled'
        if not managed.running:
            return False, f'exited {managed.returncode}'
        if check.kind == 'process':
            if time.time() - started >= .15:
                return True, 'process alive'
        elif check.kind == 'port':
            try:
                port = int(check.target)
            except (TypeError, ValueError):
                return False, 'invalid port readiness target'
            if check_port(check.host, port):
                return True, f'{check.host}:{port} listening'
        elif check.kind == 'delay':
            try:
                delay = max(0.0, float(check.target or 0))
            except ValueError:
                return False, 'invalid delay readiness target'
            if time.time() - started >= delay:
                return True, f'{delay:g}s elapsed'
        else:
            return False, f'unknown readiness kind {check.kind}'
        if time.time() >= deadline:
            return False, f'timed out waiting for {readiness_description(check)}'
        time.sleep(poll)


class ManagedProcess:
    def __init__(self, config: RunConfig, project: Project):
        self.config = config
        self.project = project
        self.process: subprocess.Popen | None = None
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self.lines: list[str] = []
        self.returncode: int | None = None
        self._thread: threading.Thread | None = None

    def start(self, on_line: Callable[[str], None] | None = None, on_exit: Callable[[int], None] | None = None) -> int:
        if self.process and self.process.poll() is None:
            raise RuntimeError('Process already running')
        cwd = self.config.cwd or self.project.path
        env = os.environ.copy()
        env.update(self.config.env)
        self.process = subprocess.Popen(
            self.config.command, cwd=cwd, env=env, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        self.started_at = time.time()
        self.ended_at = None
        self.returncode = None
        self._thread = threading.Thread(target=self._pump, args=(on_line, on_exit), daemon=True)
        self._thread.start()
        return self.process.pid

    def _pump(self, on_line, on_exit) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            text = line.rstrip('\n')
            self.lines.append(text)
            if len(self.lines) > 5000:
                del self.lines[:1000]
            if on_line:
                on_line(text)
        self.returncode = self.process.wait()
        self.ended_at = time.time()
        try:
            self.process.stdout.close()
        except Exception:
            pass
        if on_exit:
            on_exit(self.returncode)

    def stop(self, grace: float = 2.0) -> None:
        if not self.process or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self.process.kill()

    @property
    def running(self) -> bool:
        return bool(self.process and self.process.poll() is None)


class SessionController:
    def __init__(
        self,
        state: WorkspaceState,
        session: WorkspaceSession,
        on_event: Callable[[SessionEvent], None] | None = None,
        on_line: Callable[[Service, str], None] | None = None,
    ):
        self.state = state
        self.session = session
        self.on_event = on_event
        self.on_line = on_line
        self.processes: dict[str, ManagedProcess] = {}
        self.ready: set[str] = set()
        self.failed: set[str] = set()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self.status = 'IDLE'

    def _emit(self, kind: str, message: str, service_id: str | None = None) -> None:
        event = SessionEvent(time.time(), self.session.id, service_id, kind, message)
        self.state.session_history.append(event)
        self.state.session_history[:] = self.state.session_history[-500:]
        if self.on_event:
            self.on_event(event)

    def _service(self, service_id: str) -> Service | None:
        return next((s for s in self.state.services if s.id == service_id), None)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError('Session is already starting')
        if self.running:
            raise RuntimeError('Session already has running services')
        self._cancel.clear()
        self.ready.clear()
        self.failed.clear()
        self.status = 'STARTING'
        self._thread = threading.Thread(target=self._start_worker, daemon=True)
        self._thread.start()

    def _start_worker(self) -> None:
        try:
            order = topological_service_order(self.state.services, self.session.service_ids)
        except ValueError as exc:
            self.status = 'FAILED'
            self._emit('error', str(exc))
            return
        self._emit('session-start', f'Starting {self.session.name}')
        for service in order:
            if self._cancel.is_set():
                self.status = 'STOPPED'
                self._emit('session-stop', 'Start cancelled')
                return
            project = service_project(service, self.state)
            if not project or not Path(project.path).is_dir():
                self.failed.add(service.id)
                self.status = 'FAILED'
                self._emit('error', f'{service.name}: project is unavailable', service.id)
                if service.failure_policy == 'stop_dependents':
                    self.stop()
                    return
                continue
            blocked = [dep for dep in service.depends_on if dep in self.failed]
            if blocked:
                self.failed.add(service.id)
                self._emit('blocked', f'{service.name}: dependency failed', service.id)
                continue
            config = RunConfig(service.id, service.name, service.command, service.cwd, dict(service.env))
            managed = ManagedProcess(config, project)
            self.processes[service.id] = managed
            try:
                pid = managed.start(
                    lambda line, s=service: self.on_line(s, line) if self.on_line else None,
                    lambda rc, s=service: self._process_exit(s, rc),
                )
            except Exception as exc:
                self.failed.add(service.id)
                self._emit('error', f'{service.name}: {exc}', service.id)
                if service.failure_policy == 'stop_dependents':
                    self.stop()
                    self.status = 'FAILED'
                    return
                continue
            self._emit('service-start', f'{service.name} started · pid {pid}', service.id)
            ok, detail = wait_for_readiness(service, managed, cancel=self._cancel)
            if not ok:
                self.failed.add(service.id)
                self._emit('not-ready', f'{service.name}: {detail}', service.id)
                if service.failure_policy == 'stop_dependents':
                    self.stop()
                    self.status = 'FAILED'
                    return
            else:
                self.ready.add(service.id)
                self._emit('ready', f'{service.name}: {detail}', service.id)
        if self._cancel.is_set():
            self.status = 'STOPPED'
        elif self.failed:
            self.status = 'DEGRADED'
        else:
            self.status = 'RUNNING'
            self._emit('session-ready', f'{self.session.name} is ready')

    def _process_exit(self, service: Service, returncode: int) -> None:
        self.ready.discard(service.id)
        intentional = self._cancel.is_set()
        self._emit('service-exit', f'{service.name} exited {returncode}', service.id)
        if intentional:
            return
        if returncode != 0:
            self.failed.add(service.id)
            if service.failure_policy == 'stop_dependents':
                dependents = service_dependents(self.state.services, service.id)
                for dependent in dependents:
                    proc = self.processes.get(dependent.id)
                    if proc and proc.running:
                        proc.stop()
                        self._emit('cascade-stop', f'{dependent.name} stopped because {service.name} failed', dependent.id)
                self.status = 'DEGRADED'

    def stop(self) -> None:
        self._cancel.set()
        try:
            order = topological_service_order(self.state.services, self.session.service_ids)
        except ValueError:
            order = [self._service(sid) for sid in self.session.service_ids]
            order = [s for s in order if s]
        if self.session.stop_reverse_order:
            order = list(reversed(order))
        for service in order:
            managed = self.processes.get(service.id)
            if managed and managed.running:
                self._emit('service-stop', f'Stopping {service.name}', service.id)
                managed.stop()
        self.ready.clear()
        self.status = 'STOPPED'
        self._emit('session-stop', f'{self.session.name} stopped')

    @property
    def running(self) -> bool:
        return any(p.running for p in self.processes.values())

    def service_status(self, service_id: str) -> str:
        process = self.processes.get(service_id)
        if service_id in self.failed:
            return 'FAILED'
        if service_id in self.ready:
            return 'READY'
        if process and process.running:
            return 'STARTING'
        if process and process.returncode is not None:
            return f'EXIT {process.returncode}'
        return 'IDLE'
