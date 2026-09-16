from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
import json
import os
import re
import signal
import subprocess
import time
import urllib.parse
import uuid

from switchyard_core import (
    ReadinessCheck,
    Service,
    STATE_DIR,
    WorkspaceSession,
    WorkspaceState,
    topological_service_order,
    validate_service_graph,
)

RECOVERY_FILE = STATE_DIR / 'recovery.json'
SNAPSHOT_DIR = STATE_DIR / 'snapshots'
TEMPLATE_VERSION = 1
SNAPSHOT_VERSION = 1


@dataclass(frozen=True)
class TopologyNode:
    service_id: str
    depth: int
    row: int
    x: float
    y: float


@dataclass(frozen=True)
class TopologyEdge:
    source_id: str
    target_id: str


@dataclass(frozen=True)
class PortClaim:
    host: str
    port: int
    service_ids: tuple[str, ...]

    @property
    def conflict(self) -> bool:
        return len(self.service_ids) > 1


@dataclass(frozen=True)
class RecoveryProcess:
    service_id: str
    pid: int
    alive: bool


def _session_services(state: WorkspaceState, session: WorkspaceSession) -> list[Service]:
    return topological_service_order(state.services, session.service_ids)


def topology_layout(
    services: Iterable[Service],
    selected_ids: Iterable[str] | None = None,
    width: float = 1000,
    height: float = 620,
    padding_x: float = 120,
    padding_y: float = 80,
) -> tuple[list[TopologyNode], list[TopologyEdge]]:
    """Lay a dependency DAG out in deterministic left-to-right layers."""
    ordered = topological_service_order(list(services), selected_ids)
    by_id = {service.id: service for service in ordered}
    depth: dict[str, int] = {}
    for service in ordered:
        deps = [depth[dep] for dep in service.depends_on if dep in depth]
        depth[service.id] = 1 + max(deps) if deps else 0

    layers: dict[int, list[Service]] = {}
    for service in ordered:
        layers.setdefault(depth[service.id], []).append(service)
    max_depth = max(layers, default=0)
    usable_width = max(1.0, width - 2 * padding_x)
    usable_height = max(1.0, height - 2 * padding_y)
    nodes: list[TopologyNode] = []
    for layer_depth in sorted(layers):
        layer = layers[layer_depth]
        x = padding_x + (usable_width * layer_depth / max(1, max_depth))
        for row, service in enumerate(layer):
            y = padding_y + usable_height * (row + 1) / (len(layer) + 1)
            nodes.append(TopologyNode(service.id, layer_depth, row, x, y))

    edges = [
        TopologyEdge(dep, service.id)
        for service in ordered
        for dep in service.depends_on
        if dep in by_id
    ]
    return nodes, edges


def _readiness_port(service: Service) -> tuple[str, int] | None:
    check = service.readiness
    if check.kind == 'port':
        try:
            return check.host or '127.0.0.1', int(check.target)
        except (TypeError, ValueError):
            return None
    if check.kind == 'http':
        parsed = urllib.parse.urlparse(check.target)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            return None
        try:
            port = parsed.port
        except ValueError:
            return None
        return parsed.hostname, port or (443 if parsed.scheme == 'https' else 80)
    return None


def port_claims(services: Iterable[Service]) -> list[PortClaim]:
    claims: dict[tuple[str, int], list[str]] = {}
    for service in services:
        endpoint = _readiness_port(service)
        if endpoint:
            claims.setdefault(endpoint, []).append(service.id)
    return [
        PortClaim(host, port, tuple(ids))
        for (host, port), ids in sorted(claims.items(), key=lambda item: (item[0][0], item[0][1]))
    ]


def pid_alive(pid: int) -> bool:
    try:
        if int(pid) <= 0:
            return False
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OSError, ValueError):
        return False


def terminate_pid_tree(pid: int, timeout: float = 4.0) -> bool:
    """Terminate a process tree previously started by Switchyard.

    This is only called after an explicit recovery action in the UI.
    """
    if not pid_alive(pid):
        return True
    try:
        if os.name == 'nt':
            result = subprocess.run(
                ['taskkill', '/PID', str(int(pid)), '/T', '/F'],
                capture_output=True,
                text=True,
                timeout=max(1.0, timeout),
            )
            return result.returncode == 0 or not pid_alive(pid)
        os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
        deadline = time.time() + timeout
        while time.time() < deadline and pid_alive(pid):
            time.sleep(.05)
        if pid_alive(pid):
            os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
        return not pid_alive(pid)
    except Exception:
        return not pid_alive(pid)


def recovery_marker(path: Path = RECOVERY_FILE) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def begin_recovery_journal(path: Path = RECOVERY_FILE) -> dict | None:
    """Return a previous unclean-run marker and arm a marker for this run."""
    previous = recovery_marker(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = {
        'version': 2,
        'pid': os.getpid(),
        'started_at': time.time(),
        'active_session_id': None,
        'active_session_name': None,
        'processes': {},
    }
    _atomic_json(path, current)
    return previous


def update_recovery_journal(
    session: WorkspaceSession | None,
    processes: dict[str, int] | None = None,
    path: Path = RECOVERY_FILE,
) -> None:
    data = recovery_marker(path) or {
        'version': 2,
        'pid': os.getpid(),
        'started_at': time.time(),
    }
    data['active_session_id'] = session.id if session else None
    data['active_session_name'] = session.name if session else None
    data['processes'] = {str(k): int(v) for k, v in (processes or {}).items() if v}
    data['updated_at'] = time.time()
    _atomic_json(path, data)


def recovery_processes(marker: dict | None) -> list[RecoveryProcess]:
    if not marker:
        return []
    rows = []
    for service_id, raw_pid in (marker.get('processes') or {}).items():
        try:
            pid = int(raw_pid)
        except (TypeError, ValueError):
            continue
        rows.append(RecoveryProcess(str(service_id), pid, pid_alive(pid)))
    return rows


def clean_recovery_journal(path: Path = RECOVERY_FILE) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    temp.replace(path)


def session_template(state: WorkspaceState, session: WorkspaceSession) -> dict:
    services = _session_services(state, session)
    projects = {project.id: project for project in state.projects}
    names = {service.id: service.name for service in services}
    if len(set(names.values())) != len(names):
        raise ValueError('Service names must be unique inside an exported session template')
    entries = []
    for service in services:
        project = projects.get(service.project_id)
        if not project:
            raise ValueError(f'{service.name} references a missing project')
        entries.append({
            'name': service.name,
            'project': project.name,
            'command': service.command,
            'cwd': service.cwd,
            # Environment values deliberately do not travel in templates.
            'environment_keys': sorted(service.env),
            'depends_on': [names[dep] for dep in service.depends_on if dep in names],
            'readiness': asdict(service.readiness),
            'failure_policy': service.failure_policy,
        })
    return {
        'format': 'switchyard-session',
        'version': TEMPLATE_VERSION,
        'name': session.name,
        'services': entries,
    }


def export_session_template(state: WorkspaceState, session: WorkspaceSession, path: str | Path) -> Path:
    output = Path(path)
    _atomic_json(output, session_template(state, session))
    return output


def _mapped_project(state: WorkspaceState, template_name: str, project_map: dict[str, str] | None):
    if project_map and template_name in project_map:
        wanted = project_map[template_name]
        return next((p for p in state.projects if p.id == wanted or p.name.lower() == str(wanted).lower()), None)
    return next((p for p in state.projects if p.name.lower() == template_name.lower()), None)


def import_session_template(
    state: WorkspaceState,
    data: dict,
    project_map: dict[str, str] | None = None,
) -> tuple[WorkspaceSession, list[Service]]:
    if data.get('format') != 'switchyard-session' or int(data.get('version', 0)) != TEMPLATE_VERSION:
        raise ValueError('Unsupported Switchyard session template')
    entries = data.get('services')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Template does not contain services')
    service_names = [str(item.get('name', '')).strip() for item in entries]
    if any(not name for name in service_names) or len(set(service_names)) != len(service_names):
        raise ValueError('Template service names must be non-empty and unique')

    missing_projects = sorted({
        str(item.get('project', '')).strip()
        for item in entries
        if not _mapped_project(state, str(item.get('project', '')).strip(), project_map)
    })
    if missing_projects:
        raise ValueError('Map or add matching project(s) before import: ' + ', '.join(missing_projects))

    id_by_name = {name: uuid.uuid4().hex for name in service_names}
    services: list[Service] = []
    for item, name in zip(entries, service_names):
        template_project = str(item.get('project', '')).strip()
        project = _mapped_project(state, template_project, project_map)
        assert project is not None
        dep_names = [str(value) for value in item.get('depends_on', [])]
        unknown = [dep for dep in dep_names if dep not in id_by_name]
        if unknown:
            raise ValueError(f'{name} references unknown dependency: {", ".join(unknown)}')
        readiness_data = item.get('readiness') or {}
        readiness = ReadinessCheck(
            kind=readiness_data.get('kind', 'process'),
            target=str(readiness_data.get('target', '')),
            timeout=float(readiness_data.get('timeout', 30.0)),
            host=readiness_data.get('host', '127.0.0.1'),
        )
        service = Service(
            id_by_name[name],
            project.id,
            name,
            str(item.get('command', '')).strip(),
            item.get('cwd') or None,
            {},
            [id_by_name[dep] for dep in dep_names],
            readiness,
            item.get('failure_policy', 'stop_dependents'),
        )
        if not service.command:
            raise ValueError(f'{name} has no command')
        services.append(service)
    errors = validate_service_graph(services)
    if errors:
        raise ValueError('; '.join(errors))

    base_name = str(data.get('name') or 'Imported session').strip()
    existing_names = {session.name.lower() for session in state.sessions}
    session_name = base_name
    suffix = 2
    while session_name.lower() in existing_names:
        session_name = f'{base_name} {suffix}'
        suffix += 1
    session = WorkspaceSession(uuid.uuid4().hex, session_name, [id_by_name[name] for name in service_names])
    return session, services


def load_session_template(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'Could not read session template: {exc}') from exc
    if not isinstance(data, dict):
        raise ValueError('Session template root must be an object')
    return data


def snapshot_payload(state: WorkspaceState, session: WorkspaceSession, runtime_metadata: dict | None = None) -> dict:
    """Create a secret-free restorable session snapshot."""
    return {
        'format': 'switchyard-snapshot',
        'version': SNAPSHOT_VERSION,
        'created_at': time.time(),
        'session': session_template(state, session),
        'runtime': runtime_metadata or {},
    }


def _slug(value: str) -> str:
    slug = re.sub(r'[^a-zA-Z0-9._-]+', '-', value.strip()).strip('-').lower()
    return slug or 'session'


def save_session_snapshot(
    state: WorkspaceState,
    session: WorkspaceSession,
    runtime_metadata: dict | None = None,
    directory: str | Path = SNAPSHOT_DIR,
) -> Path:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    output = root / f'{_slug(session.name)}-{stamp}.json'
    _atomic_json(output, snapshot_payload(state, session, runtime_metadata))
    return output


def list_session_snapshots(directory: str | Path = SNAPSHOT_DIR) -> list[Path]:
    root = Path(directory)
    if not root.exists():
        return []
    return sorted(root.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)


def load_session_snapshot(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'Could not read session snapshot: {exc}') from exc
    if not isinstance(data, dict) or data.get('format') != 'switchyard-snapshot' or int(data.get('version', 0)) != SNAPSHOT_VERSION:
        raise ValueError('Unsupported Switchyard session snapshot')
    if not isinstance(data.get('session'), dict):
        raise ValueError('Snapshot has no session template')
    return data


def import_session_snapshot(
    state: WorkspaceState,
    snapshot: dict,
    project_map: dict[str, str] | None = None,
) -> tuple[WorkspaceSession, list[Service], dict]:
    session, services = import_session_template(state, snapshot['session'], project_map=project_map)
    return session, services, dict(snapshot.get('runtime') or {})
