from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import time

from switchyard_core import WorkspaceState, git_snapshot
from switchyard_topology import port_claims


@dataclass(frozen=True)
class PaletteItem:
    id: str
    label: str
    hint: str = ''
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class DashboardProject:
    id: str
    name: str
    path: str
    pinned: bool
    last_opened: float
    exists: bool
    git: bool
    branch: str
    dirty: bool
    changed: int


@dataclass(frozen=True)
class DashboardSummary:
    projects: tuple[DashboardProject, ...]
    dirty_count: int
    missing_count: int
    running_sessions: int
    ready_services: int
    total_services: int
    last_failure: str
    attention: tuple[str, ...]
    port_conflicts: tuple[str, ...]


def rank_palette(items: Iterable[PaletteItem], query: str, limit: int = 30) -> list[PaletteItem]:
    words = [part.casefold() for part in query.strip().split() if part]
    scored = []
    for index, item in enumerate(items):
        haystack = ' '.join((item.label, item.hint, *item.keywords)).casefold()
        if words and not all(word in haystack for word in words):
            continue
        score = 0
        label = item.label.casefold()
        for word in words:
            if label.startswith(word): score += 40
            elif f' {word}' in label: score += 20
            else: score += 8
        if not words: score = -index
        scored.append((score, -index, item))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [row[2] for row in scored[:max(1, limit)]]


def _last_failure(state: WorkspaceState) -> str:
    bad = {'service-failed','restart-failed','preflight-error','session-degraded','cascade-stop','session-failed'}
    for event in reversed(state.session_history):
        if event.kind in bad or 'fail' in event.kind or 'degrad' in event.kind:
            stamp = time.strftime('%Y-%m-%d %H:%M', time.localtime(event.timestamp))
            return f'{stamp} · {event.message}'
    return ''


def dashboard_summary(state: WorkspaceState, session_statuses: dict[str, str] | None = None, service_statuses: dict[str, str] | None = None) -> DashboardSummary:
    session_statuses = session_statuses or {}
    service_statuses = service_statuses or {}
    rows = []
    attention = []
    dirty_count = 0
    missing_count = 0
    for project in state.projects:
        path = Path(project.path)
        exists = path.is_dir()
        git = git_snapshot(path) if exists else {'git':False,'branch':'','dirty':False,'changed':0}
        dirty = bool(git.get('dirty'))
        changed = int(git.get('changed') or 0)
        if dirty:
            dirty_count += 1
            attention.append(f'{project.name}: {changed} uncommitted change(s)')
        if not exists:
            missing_count += 1
            attention.append(f'{project.name}: project folder is missing')
        rows.append(DashboardProject(project.id, project.name, project.path, project.pinned, float(project.last_opened or 0), exists, bool(git.get('git')), str(git.get('branch') or ''), dirty, changed))
    rows.sort(key=lambda row: (not row.pinned, -row.last_opened, row.name.casefold()))

    conflicts = []
    names = {service.id: service.name for service in state.services}
    for claim in port_claims(state.services):
        if claim.conflict:
            label = f'{claim.host}:{claim.port} · ' + ', '.join(names.get(sid, sid) for sid in claim.service_ids)
            conflicts.append(label)
            attention.append(f'Port conflict: {label}')

    last_failure = _last_failure(state)
    if last_failure:
        attention.append('Last runtime issue: ' + last_failure)
    running_sessions = sum(1 for status in session_statuses.values() if status in {'STARTING','RUNNING','DEGRADED'})
    ready_services = sum(1 for status in service_statuses.values() if status == 'READY')
    return DashboardSummary(tuple(rows), dirty_count, missing_count, running_sessions, ready_services, len(state.services), last_failure, tuple(attention[:20]), tuple(conflicts))
