"""Headless V1 first-run smoke test.

Exercises the minimum real user journey without creating a GUI or touching the
caller's ~/.switchyard directory: empty first run, persistence, preflight,
service startup, readiness, shutdown, and reload.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from switchyard_core import ReadinessCheck, Service, WorkspaceSession, WorkspaceState, load_state, new_project, save_state
from switchyard_runtime import ResilientSessionController, RuntimeSettings, load_runtime, preflight_ok, save_runtime, session_preflight


def wait_until(predicate, timeout=5.0, interval=.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='switchyard-v1-smoke-') as raw:
        root = Path(raw)
        state_path = root / 'profile' / 'state.json'
        runtime_path = root / 'profile' / 'runtime.json'

        # A genuine first run must be safe with no files or profile directory.
        state = load_state(state_path)
        runtime = load_runtime(runtime_path)
        assert state.projects == []
        assert runtime.profiles == []
        assert not state_path.exists()
        assert not runtime_path.exists()

        project_dir = root / 'Demo Project – smoke'
        project_dir.mkdir()
        worker = project_dir / 'worker.py'
        worker.write_text('import time\nprint("ready", flush=True)\ntime.sleep(2)\n', encoding='utf-8')

        project = new_project(project_dir, 'First project')
        service = Service(
            'service', project.id, 'Smoke service', f'"{sys.executable}" "{worker}"',
            readiness=ReadinessCheck('process', '', 1.5),
        )
        session = WorkspaceSession('session', 'First workspace', ['service'])
        state = WorkspaceState([project], project.id, services=[service], sessions=[session])

        save_state(state, state_path)
        save_runtime(runtime, runtime_path)
        state = load_state(state_path)
        runtime = load_runtime(runtime_path)
        assert state.selected_project == project.id
        assert state.sessions[0].name == 'First workspace'
        assert preflight_ok(session_preflight(state, state.sessions[0], runtime))

        controller = ResilientSessionController(state, state.sessions[0], runtime)
        controller.start()
        try:
            assert wait_until(lambda: controller.status == 'RUNNING', timeout=4), controller.status
            assert controller.processes['service'].running
        finally:
            controller.stop()
        assert wait_until(lambda: not controller.running, timeout=3)
        assert controller.status == 'STOPPED'

        save_state(state, state_path)
        reloaded = load_state(state_path)
        assert reloaded.projects[0].name == 'First project'
        assert reloaded.sessions[0].name == 'First workspace'

    print('Switchyard V1 first-run smoke test passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
