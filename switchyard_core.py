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
STATE_VERSION = 2
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
class WorkspaceState:
    projects: list[Project] = field(default_factory=list)
    selected_project: str | None = None
    run_history: list[RunRecord] = field(default_factory=list)
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


def load_state(path: Path = STATE_FILE) -> WorkspaceState:
    if not path.exists():
        return WorkspaceState()
    data = json.loads(path.read_text(encoding='utf-8'))
    return WorkspaceState(
        projects=[_project_from_dict(x) for x in data.get('projects', [])],
        selected_project=data.get('selected_project'),
        run_history=[_record_from_dict(x) for x in data.get('run_history', [])],
        version=STATE_VERSION,
    )


def save_state(state: WorkspaceState, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state.version = STATE_VERSION
    state.run_history[:] = state.run_history[-250:]
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding='utf-8')
    tmp.replace(path)


def new_project(path: str | Path, name: str | None = None) -> Project:
    p = Path(path).expanduser().resolve()
    return Project(uuid.uuid4().hex, name or p.name, str(p), last_opened=time.time())


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
    return [
        RunConfig(uuid.uuid4().hex, t['name'], t['command'])
        for t in detected['tasks'] if t['command'] not in existing
    ]


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
            'ok': available,
            'detail': 'available' if available else 'executable not found on PATH',
        })
    detected = detect_project(p)
    for port in detected['ports']:
        open_ = check_port('127.0.0.1', port)
        checks.append({
            'name': f'Local port {port}', 'kind': 'port', 'target': str(port),
            'ok': open_, 'detail': 'listening' if open_ else 'not listening',
        })
    return checks


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
            self.config.command,
            cwd=cwd,
            env=env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
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
