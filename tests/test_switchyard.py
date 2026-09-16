import sys
import tempfile
import time
import unittest
from pathlib import Path

from switchyard_core import (
    ManagedProcess, Project, ReadinessCheck, RunConfig, Service, SessionController,
    WorkspaceSession, WorkspaceState, detect_project, load_state, new_project,
    save_state, topological_service_order, validate_service_graph, wait_for_readiness,
)


class SwitchyardTests(unittest.TestCase):
    def test_state_roundtrip_v3(self):
        with tempfile.TemporaryDirectory() as d:
            sf = Path(d) / 'state.json'
            project = new_project(d, 'Demo')
            project.run_configs.append(RunConfig('run', 'Echo', f'"{sys.executable}" -c "print(123)"'))
            service = Service('api', project.id, 'API', f'"{sys.executable}" -c "import time;time.sleep(.2)"', readiness=ReadinessCheck('delay', '0.05', 2))
            session = WorkspaceSession('dev', 'Development', [service.id])
            state = WorkspaceState([project], project.id, services=[service], sessions=[session])
            save_state(state, sf)
            loaded = load_state(sf)
            self.assertEqual(loaded.version, 3)
            self.assertEqual(loaded.services[0].name, 'API')
            self.assertEqual(loaded.services[0].readiness.kind, 'delay')
            self.assertEqual(loaded.sessions[0].service_ids, ['api'])

    def test_v1_state_migrates(self):
        with tempfile.TemporaryDirectory() as d:
            sf = Path(d) / 'state.json'
            sf.write_text('{"projects":[{"id":"p","name":"Old","path":"%s","run_configs":[]}],"selected_project":"p"}' % d.replace('\\','\\\\'), encoding='utf-8')
            state = load_state(sf)
            self.assertEqual(state.version, 3)
            self.assertEqual(state.projects[0].name, 'Old')
            self.assertEqual(state.services, [])

    def test_snapshot_and_detection(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'package.json').write_text('{"scripts":{"dev":"vite"},"dependencies":{"react":"x"}}', encoding='utf-8')
            detected = detect_project(p)
            self.assertIn('Node.js', detected['stacks'])
            self.assertIn('React', detected['stacks'])
            self.assertTrue(any(t['command'] == 'npm run dev' for t in detected['tasks']))

    def test_managed_process(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d)
            config = RunConfig('x', 'test', f'"{sys.executable}" -c "print(\'ok\')"')
            managed = ManagedProcess(config, project); managed.start()
            for _ in range(100):
                if managed.returncode is not None: break
                time.sleep(.01)
            self.assertEqual(managed.returncode, 0)
            self.assertIn('ok', managed.lines)

    def test_service_order_includes_dependencies(self):
        project = Project('p', 'P', '.')
        db = Service('db', project.id, 'DB', 'db')
        api = Service('api', project.id, 'API', 'api', depends_on=['db'])
        web = Service('web', project.id, 'WEB', 'web', depends_on=['api'])
        order = topological_service_order([web, db, api], ['web'])
        self.assertEqual([s.id for s in order], ['db', 'api', 'web'])

    def test_service_cycle_is_rejected(self):
        a = Service('a', 'p', 'A', 'a', depends_on=['b'])
        b = Service('b', 'p', 'B', 'b', depends_on=['a'])
        errors = validate_service_graph([a, b])
        self.assertTrue(errors)
        self.assertIn('cycle', errors[0].lower())

    def test_delay_readiness(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d)
            service = Service('svc', project.id, 'svc', f'"{sys.executable}" -c "import time;time.sleep(.4)"', readiness=ReadinessCheck('delay', '0.05', 1))
            managed = ManagedProcess(RunConfig(service.id, service.name, service.command), project); managed.start()
            ok, detail = wait_for_readiness(service, managed, poll=.01)
            self.assertTrue(ok, detail)
            managed.stop()
            for _ in range(100):
                if managed.returncode is not None: break
                time.sleep(.01)
            self.assertIsNotNone(managed.returncode)

    def test_session_controller_starts_dependencies(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Demo')
            cmd = f'"{sys.executable}" -c "import time;time.sleep(.6)"'
            first = Service('first', project.id, 'FIRST', cmd, readiness=ReadinessCheck('delay', '0.03', 1))
            second = Service('second', project.id, 'SECOND', cmd, depends_on=['first'], readiness=ReadinessCheck('delay', '0.03', 1))
            state = WorkspaceState([project], project.id, services=[first, second], sessions=[WorkspaceSession('s', 'Session', ['second'])])
            controller = SessionController(state, state.sessions[0]); controller.start()
            for _ in range(200):
                if controller.status in {'RUNNING', 'FAILED', 'DEGRADED'}: break
                time.sleep(.01)
            self.assertEqual(controller.status, 'RUNNING')
            self.assertEqual(controller.ready, {'first', 'second'})
            kinds = [e.kind for e in state.session_history]
            self.assertIn('session-ready', kinds)
            controller.stop()
            for _ in range(100):
                if not controller.running: break
                time.sleep(.01)
            self.assertFalse(controller.running)


if __name__ == '__main__':
    unittest.main()
