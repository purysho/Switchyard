from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import os
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser


@dataclass(frozen=True)
class ToolSpec:
    key: str
    name: str
    repo_name: str
    executable: str
    source_entrypoint: str
    github_url: str
    purpose: str


@dataclass(frozen=True)
class ToolLaunch:
    spec: ToolSpec
    command: tuple[str, ...]
    location: str
    mode: str


TOOLS = {
    'blackbox': ToolSpec('blackbox', 'BLACKBOX', 'BLACKBOX', 'BLACKBOX.exe', 'blackbox_desktop.pyw', 'https://github.com/purysho/BLACKBOX', 'Inspect this repository'),
    'needle': ToolSpec('needle', 'Needle', 'Needle', 'Needle.exe', 'needle_desktop.pyw', 'https://github.com/purysho/Needle', 'Search this workspace'),
    'relay': ToolSpec('relay', 'Relay', 'Relay', 'Relay.exe', 'relay_desktop.pyw', 'https://github.com/purysho/Relay', 'Inspect this endpoint'),
    'pulse': ToolSpec('pulse', 'Pulse', 'Pulse', 'Pulse.exe', 'pulse_desktop.pyw', 'https://github.com/purysho/Pulse', 'Inspect this process'),
}


def _python_gui() -> str | None:
    names = ['pyw', 'pythonw', 'python3', 'python'] if os.name == 'nt' else ['python3', 'python']
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    if not getattr(sys, 'frozen', False):
        return sys.executable
    return None


def _candidate_roots(project_paths: Iterable[str] = (), extra_roots: Iterable[str | Path] = ()) -> list[Path]:
    roots: list[Path] = []
    for raw in extra_roots:
        try:
            roots.append(Path(raw).expanduser().resolve())
        except OSError:
            pass
    for raw in project_paths:
        try:
            project = Path(raw).expanduser().resolve()
        except OSError:
            continue
        roots.extend([project.parent, project.parent.parent])
    try:
        cwd = Path.cwd().resolve()
        roots.extend([cwd, cwd.parent])
    except OSError:
        pass
    roots.extend([
        Path.home() / 'Projects',
        Path.home() / 'projects',
        Path.home() / 'Apps',
        Path.home() / '.local' / 'bin',
    ])
    local_app = os.environ.get('LOCALAPPDATA')
    if local_app:
        roots.extend([Path(local_app) / 'Programs' / 'Purysho', Path(local_app) / 'Purysho'])
    unique: list[Path] = []
    seen = set()
    for root in roots:
        key = os.path.normcase(str(root))
        if key not in seen:
            seen.add(key); unique.append(root)
    return unique


def _launch_from_path(spec: ToolSpec, path: Path) -> ToolLaunch | None:
    if path.is_file():
        if path.name.lower() == spec.executable.lower() or path.suffix.lower() == '.exe':
            return ToolLaunch(spec, (str(path),), str(path), 'executable')
        if path.name == spec.source_entrypoint:
            python = _python_gui()
            if python:
                return ToolLaunch(spec, (python, str(path)), str(path), 'source')
        return None
    if not path.is_dir():
        return None
    exe_candidates = [path / spec.executable, path / 'dist' / spec.executable]
    for candidate in exe_candidates:
        if candidate.is_file():
            return ToolLaunch(spec, (str(candidate),), str(candidate), 'executable')
    source = path / spec.source_entrypoint
    if source.is_file():
        python = _python_gui()
        if python:
            return ToolLaunch(spec, (python, str(source)), str(source), 'source')
    return None


def discover_tool(key: str, project_paths: Iterable[str] = (), extra_roots: Iterable[str | Path] = ()) -> ToolLaunch | None:
    spec = TOOLS[key]
    override = os.environ.get(f'PURYSHO_{spec.key.upper()}_PATH')
    if override:
        found = _launch_from_path(spec, Path(override).expanduser())
        if found:
            return found

    for candidate_name in (spec.executable, Path(spec.executable).stem, spec.name):
        found_path = shutil.which(candidate_name)
        if found_path:
            found = _launch_from_path(spec, Path(found_path))
            if found:
                return found

    for root in _candidate_roots(project_paths, extra_roots):
        for candidate in (root / spec.repo_name, root):
            found = _launch_from_path(spec, candidate)
            if found:
                return found
    return None


def launch_tool(key: str, args: Iterable[str] = (), project_paths: Iterable[str] = (), extra_roots: Iterable[str | Path] = ()) -> ToolLaunch:
    launch = discover_tool(key, project_paths, extra_roots)
    if not launch:
        raise FileNotFoundError(f'{TOOLS[key].name} was not found locally')
    command = [*launch.command, *[str(value) for value in args]]
    kwargs = {'close_fds': True}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(command, **kwargs)
    return launch


def open_tool_repository(key: str) -> None:
    webbrowser.open(TOOLS[key].github_url)


def readiness_url(readiness) -> str | None:
    if not readiness:
        return None
    kind = getattr(readiness, 'kind', '')
    target = str(getattr(readiness, 'target', '') or '').strip()
    host = str(getattr(readiness, 'host', '') or '127.0.0.1')
    if kind == 'http' and target:
        parsed = urllib.parse.urlparse(target)
        return target if parsed.scheme in {'http', 'https'} and parsed.hostname else None
    if kind == 'port':
        try:
            port = int(target)
        except (TypeError, ValueError):
            return None
        return f'http://{host}:{port}/'
    return None


def handoff_args(key: str, *, project_path: str | None = None, service=None, pid: int | None = None, query: str = '') -> list[str]:
    if key == 'blackbox':
        return ['--repo', project_path] if project_path else []
    if key == 'needle':
        args = ['--root', project_path] if project_path else []
        if query:
            args.extend(['--query', query])
        return args
    if key == 'relay':
        url = readiness_url(getattr(service, 'readiness', None)) if service else None
        return ['--url', url] if url else []
    if key == 'pulse':
        return ['--pid', str(int(pid))] if pid else []
    raise KeyError(key)
