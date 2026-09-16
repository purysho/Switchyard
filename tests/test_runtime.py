import http.server
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from switchyard_core import ReadinessCheck, Service, WorkspaceSession, WorkspaceState, new_project
from switchyard_runtime import (
    EnvironmentProfile, ResilientSessionController, RuntimeSettings,
    ServiceRuntimePolicy, http_probe, load_runtime, masked_profile_rows,
    preflight_ok, resolve_profile, save_runtime, session_preflight,
    wait_for_runtime_readiness,
)


class QuietHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(204); self.end_headers()
    def log_message(self, *_args):
        pass


class RuntimeTests(unittest.TestCase):
    def test_runtime_settings_roundtrip_does_not_copy_inherited_secret(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'runtime.json'
            settings = RuntimeSettings(profiles=[EnvironmentProfile('local', 'Local', {'MODE': 'dev'}, ['TOKEN'])])
            save_runtime(settings, path)
            text = path.read_text(encoding='utf-8')
            self.assertIn('TOKEN', text)
            self.assertNotIn('super-secret-value', text)
            loaded = load_runtime(path)
            values, missing = resolve_profile(loaded.profiles[0], {'TOKEN': 'super-secret-value'})
            self.assertEqual(values['TOKEN'], 'super-secret-value')
            self.assertEqual(missing, [])

    def test_missing_inherited_environment_is_reported(self):
        profile = EnvironmentProfile('x', 'Missing', {}, ['DOES_NOT_EXIST_SWITCHYARD_TEST'])
        values, missing = resolve_profile(profile, {})
        self.assertEqual(values, {})
        self.assertEqual(missing, ['DOES_NOT_EXIST_SWITCHYARD_TEST'])
        self.assertEqual(masked_profile_rows(profile)[0][1], '••••••••')

    def test_http_probe_and_readiness(self):
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/health'
            ok, detail = http_probe(url)
            self.assertTrue(ok, detail)
            self.assertIn('204', detail)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_preflight_detects_duplicate_ports(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Demo')
            command = f'"{sys.executable}" -c "import time;time.sleep(1)"'
            a = Service('a', project.id, 'A', command, readiness=ReadinessCheck('port', '45678', 1))
            b = Service('b', project.id, 'B', command, readiness=ReadinessCheck('port', '45678', 1))
            state = WorkspaceState([project], project.id, services=[a, b], sessions=[WorkspaceSession('s', 'Dev', ['a', 'b'])])
            checks = session_preflight(state, state.sessions[0], RuntimeSettings())
            self.assertFalse(preflight_ok(checks))
            self.assertTrue(any(c.name == 'Port conflict' for c in checks))

    def test_preflight_blocks_missing_inherited_variable(self):
        key = 'SWITCHYARD_TEST_SECRET_MISSING_192837'
        os.environ.pop(key, None)
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Demo')
            service = Service('svc', project.id, 'API', f'"{sys.executable}" -c "import time;time.sleep(1)"')
            session = WorkspaceSession('session', 'Dev', ['svc'])
            state = WorkspaceState([project], project.id, services=[service], sessions=[session])
            settings = RuntimeSettings(
                profiles=[EnvironmentProfile('profile', 'Local', {}, [key])],
                session_profiles={'session': 'profile'},
            )
            checks = session_preflight(state, session, settings)
            self.assertFalse(preflight_ok(checks))
            self.assertTrue(any(c.name == 'Environment' and c.level == 'ERROR' for c in checks))

    def test_controller_applies_profile_and_starts_session(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Demo')
            script = Path(d) / 'service.py'
            script.write_text('import os,time\nprint(os.getenv("SWITCHYARD_MODE"), flush=True)\ntime.sleep(.5)\n', encoding='utf-8')
            command = f'"{sys.executable}" "{script}"'
            service = Service('svc', project.id, 'API', command, readiness=ReadinessCheck('delay', '.05', 2))
            session = WorkspaceSession('session', 'Dev', ['svc'])
            state = WorkspaceState([project], project.id, services=[service], sessions=[session])
            settings = RuntimeSettings(profiles=[EnvironmentProfile('p', 'Local', {'SWITCHYARD_MODE': 'development'})], session_profiles={'session': 'p'})
            lines = []
            controller = ResilientSessionController(state, session, settings, on_line=lambda _s, line: lines.append(line)); controller.start()
            for _ in range(200):
                if controller.status in {'RUNNING', 'FAILED', 'DEGRADED'}: break
                time.sleep(.01)
            self.assertEqual(controller.status, 'RUNNING')
            for _ in range(100):
                if lines: break
                time.sleep(.01)
            self.assertIn('development', lines)
            controller.stop()
            for _ in range(100):
                if not controller.running: break
                time.sleep(.01)
            self.assertFalse(controller.running)

    def test_restart_policy_recovers_one_failure(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Demo')
            sentinel = Path(d) / 'once.txt'
            script = Path(d) / 'flaky.py'
            script.write_text(
                'from pathlib import Path\nimport sys,time\np=Path(sys.argv[1])\n'
                'if not p.exists():\n p.write_text("x")\n sys.exit(7)\n'
                'time.sleep(.8)\n', encoding='utf-8')
            command = f'"{sys.executable}" "{script}" "{sentinel}"'
            service = Service('svc', project.id, 'Worker', command, readiness=ReadinessCheck('process', '', 1), failure_policy='continue')
            session = WorkspaceSession('session', 'Dev', ['svc'])
            state = WorkspaceState([project], project.id, services=[service], sessions=[session])
            settings = RuntimeSettings(policies=[ServiceRuntimePolicy('svc', 'on_failure', 2, .02, .05)])
            controller = ResilientSessionController(state, session, settings); controller.start()
            for _ in range(300):
                if any(e.kind == 'restart-ready' for e in state.session_history): break
                time.sleep(.01)
            self.assertTrue(any(e.kind == 'restart-scheduled' for e in state.session_history))
            self.assertTrue(any(e.kind == 'restart-ready' for e in state.session_history))
            controller.stop()


if __name__ == '__main__':
    unittest.main()
