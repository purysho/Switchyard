from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
import json
import os
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
TEMPLATE_VERSION = 1


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
    """Lay a dependency DAG out in left-to-right layers.

    Dependencies always occupy an earlier layer than their dependents. Coordinates
    are deterministic for a stable service list, which keeps the canvas from
    jumping around while runtime state changes.
    """
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


def recovery_marker(path: Path = RECOVERY_FILE) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def begin_recovery_journal(path: Path = RECOVERY_FILE) -> dict | None:
    """Return a previous unclean-run marker and arm a new marker for this run."""
    previous = recovery_marker(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = {
        'version': 1,
        'pid': os.getpid(),
        'started_at': time.time(),
        'active_session_id': None,
        'active_session_name': None,
    }
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(current, indent=2), encoding='utf-8')
    temp.replace(path)
    return previous


def update_recovery_journal(session: WorkspaceSession | None, path: Path = RECOVERY_FILE) -> None:
    data = recovery_marker(path) or {
        'version': 1,
        'pid': os.getpid(),
        'started_at': time.time(),
    }
    data['active_session_id'] = session.id if session else None
    data['active_session_name'] = session.name if session else None
    data['updated_at'] = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temp.replace(path)


def clean_recovery_journal(path: Path = RECOVERY_FILE) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


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
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(session_template(state, session), indent=2), encoding='utf-8')
    return output


def import_session_template(state: WorkspaceState, data: dict) -> tuple[WorkspaceSession, list[Service]]:
    if data.get('format') != 'switchyard-session' or int(data.get('version', 0)) != TEMPLATE_VERSION:
        raise ValueError('Unsupported Switchyard session template')
    entries = data.get('services')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Template does not contain services')
    service_names = [str(item.get('name', '')).strip() for item in entries]
    if any(not name for name in service_names) or len(set(service_names)) != len(service_names):
        raise ValueError('Template service names must be non-empty and unique')
    project_by_name = {project.name.lower(): project for project in state.projects}
    missing_projects = sorted({
        str(item.get('project', '')).strip()
        for item in entries
        if str(item.get('project', '')).strip().lower() not in project_by_name
    })
    if missing_projects:
        raise ValueError('Add matching project(s) before import: ' + ', '.join(missing_projects))

    id_by_name = {name: uuid.uuid4().hex for name in service_names}
    services: list[Service] = []
    for item, name in zip(entries, service_names):
        project = project_by_name[str(item.get('project', '')).strip().lower()]
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
        session_name = f'{base_name} {suffix}'; suffix += 1
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
