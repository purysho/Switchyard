import socketserver
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from switchyard_core import ManagedProcess, ReadinessCheck, RunConfig, Service, WorkspaceSession, WorkspaceState, new_project
from switchyard_runtime import ResilientSessionController, RuntimeSettings, ServiceRuntimePolicy, preflight_ok, session_preflight
from switchyard_topology import pid_alive, terminate_pid_tree


def wait_until(predicate, timeout=6.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


class _AcceptAndClose(socketserver.BaseRequestHandler):
    def handle(self):
        return


class LifecycleHardeningTests(unittest.TestCase):
    def test_preoccupied_readiness_port_blocks_launch_instead_of_false_ready(self):
        # Use a real accepting server rather than a bare listen() socket. Windows can
        # fill a tiny unaccepted backlog after the first preflight probe, making a
        # second probe look closed even though the listener is still alive.
        server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), _AcceptAndClose)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                project = new_project(d, 'Occupied port')
                sentinel = Path(d) / 'launched.txt'
                script = Path(d) / 'service.py'
                script.write_text(
                    'from pathlib import Path\nimport sys,time\nPath(sys.argv[1]).write_text("launched")\ntime.sleep(2)\n',
                    encoding='utf-8',
                )
                service = Service(
                    'svc', project.id, 'API', f'"{sys.executable}" "{script}" "{sentinel}"',
                    readiness=ReadinessCheck('port', str(server.server_address[1]), 1.0),
                )
                session = WorkspaceSession('session', 'Port collision', ['svc'])
                state = WorkspaceState([project], project.id, services=[service], sessions=[session])
                checks = session_preflight(state, session, RuntimeSettings())
                self.assertFalse(preflight_ok(checks))
                self.assertTrue(any(c.name == 'Port already open' and c.level == 'ERROR' for c in checks))

                controller = ResilientSessionController(state, session, RuntimeSettings())
                controller.start()
                self.assertTrue(wait_until(lambda: controller.status == 'FAILED', timeout=3))
                self.assertFalse(sentinel.exists())
                self.assertNotIn('svc', controller.processes)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_rapid_stop_then_restart_cannot_wake_stale_restart_worker(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Restart race')
            counter = Path(d) / 'count.txt'
            script = Path(d) / 'flaky.py'
            script.write_text(
                'from pathlib import Path\nimport sys,time\np=Path(sys.argv[1])\n'
                'n=int(p.read_text())+1 if p.exists() else 1\np.write_text(str(n))\n'
                'if n == 1:\n time.sleep(.05)\n sys.exit(9)\n'
                'time.sleep(2)\n',
                encoding='utf-8',
            )
            service = Service(
                'svc', project.id, 'Worker', f'"{sys.executable}" "{script}" "{counter}"',
                readiness=ReadinessCheck('process', '', 1.0), failure_policy='continue',
            )
            session = WorkspaceSession('session', 'Restart race', ['svc'])
            state = WorkspaceState([project], project.id, services=[service], sessions=[session])
            settings = RuntimeSettings(policies=[ServiceRuntimePolicy('svc', 'on_failure', 2, .5, .5)])
            controller = ResilientSessionController(state, session, settings)

            controller.start()
            self.assertTrue(wait_until(lambda: any(e.kind == 'restart-scheduled' for e in state.session_history), timeout=3))
            controller.stop()
            controller.start()
            try:
                self.assertTrue(wait_until(lambda: controller.status == 'RUNNING', timeout=3))
                self.assertEqual(controller.restart_counts.get('svc', 0), 0)
                time.sleep(.7)  # Past the stale restart's original wake-up time.
                self.assertEqual(counter.read_text(encoding='utf-8'), '2')
                self.assertTrue(controller.processes['svc'].running)
            finally:
                controller.stop()

    def test_duplicate_start_is_rejected_without_disturbing_live_session(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Double start')
            script = Path(d) / 'long.py'
            script.write_text('import time\ntime.sleep(3)\n', encoding='utf-8')
            service = Service('svc', project.id, 'Worker', f'"{sys.executable}" "{script}"', readiness=ReadinessCheck('process', '', 1))
            session = WorkspaceSession('session', 'Double start', ['svc'])
            state = WorkspaceState([project], project.id, services=[service], sessions=[session])
            controller = ResilientSessionController(state, session, RuntimeSettings())
            controller.start()
            try:
                self.assertTrue(wait_until(lambda: controller.status == 'RUNNING', timeout=3))
                generation = controller._run_generation
                pid = controller.processes['svc'].process.pid
                with self.assertRaises(RuntimeError):
                    controller.start()
                self.assertEqual(controller._run_generation, generation)
                self.assertTrue(controller.processes['svc'].running)
                self.assertEqual(controller.processes['svc'].process.pid, pid)
            finally:
                controller.stop()

    def test_relative_working_directory_resolves_from_project_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            work = root / 'frontend'
            work.mkdir()
            observed = root / 'cwd.txt'
            script = root / 'write_cwd.py'
            script.write_text(
                'from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text(str(Path.cwd()), encoding="utf-8")\n',
                encoding='utf-8',
            )
            project = new_project(root, 'Relative cwd')
            managed = ManagedProcess(
                RunConfig('cwd', 'Relative cwd', f'"{sys.executable}" "{script}" "{observed}"', cwd='frontend'),
                project,
            )
            managed.start()
            self.assertTrue(wait_until(lambda: managed.returncode is not None, timeout=4))
            self.assertEqual(managed.returncode, 0)
            self.assertEqual(Path(observed.read_text(encoding='utf-8')).resolve(), work.resolve())

    def test_missing_working_directory_is_blocked_by_preflight(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Broken cwd')
            service = Service(
                'svc',
                project.id,
                'Worker',
                f'"{sys.executable}" -c "print(1)"',
                cwd='does-not-exist',
            )
            session = WorkspaceSession('session', 'Broken cwd', ['svc'])
            state = WorkspaceState([project], project.id, services=[service], sessions=[session])
            checks = session_preflight(state, session, RuntimeSettings())

            self.assertFalse(preflight_ok(checks))
            self.assertTrue(any(
                check.name == 'Working directory'
                and check.level == 'ERROR'
                and 'does-not-exist' in check.detail
                for check in checks
            ))

    def test_missing_executable_fails_cleanly_without_lingering_process(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Missing executable')
            service = Service(
                'svc', project.id, 'Missing', 'switchyard-command-that-does-not-exist-4f391c',
                readiness=ReadinessCheck('process', '', .6), failure_policy='continue',
            )
            session = WorkspaceSession('session', 'Missing executable', ['svc'])
            state = WorkspaceState([project], project.id, services=[service], sessions=[session])
            controller = ResilientSessionController(state, session, RuntimeSettings())
            controller.start()
            try:
                self.assertTrue(wait_until(lambda: controller.status in {'DEGRADED', 'FAILED'}, timeout=4))
                self.assertIn('svc', controller.failed)
                proc = controller.processes.get('svc')
                self.assertTrue(proc is None or not proc.running)
            finally:
                controller.stop()

    def test_missing_project_is_blocked_before_process_launch(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / 'deleted-project'
            missing.mkdir()
            project = new_project(missing, 'Deleted project')
            missing.rmdir()
            service = Service('svc', project.id, 'Worker', f'"{sys.executable}" -c "import time;time.sleep(2)"')
            session = WorkspaceSession('session', 'Missing project', ['svc'])
            state = WorkspaceState([project], project.id, services=[service], sessions=[session])
            controller = ResilientSessionController(state, session, RuntimeSettings())
            controller.start()
            self.assertTrue(wait_until(lambda: controller.status == 'FAILED', timeout=3))
            self.assertNotIn('svc', controller.processes)
            self.assertTrue(any(e.kind == 'preflight-error' for e in state.session_history))

    def test_concurrent_failures_block_shared_dependent_without_launching_it(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Parallel failures')
            fail = Path(d) / 'fail.py'
            fail.write_text('import sys,time\ntime.sleep(.08)\nsys.exit(7)\n', encoding='utf-8')
            sleeper = Path(d) / 'dependent.py'
            sentinel = Path(d) / 'dependent-started.txt'
            sleeper.write_text('from pathlib import Path\nimport sys,time\nPath(sys.argv[1]).write_text("started")\ntime.sleep(2)\n', encoding='utf-8')
            a = Service('a', project.id, 'A', f'"{sys.executable}" "{fail}"', readiness=ReadinessCheck('process', '', .8), failure_policy='continue')
            b = Service('b', project.id, 'B', f'"{sys.executable}" "{fail}"', readiness=ReadinessCheck('process', '', .8), failure_policy='continue')
            c = Service('c', project.id, 'C', f'"{sys.executable}" "{sleeper}" "{sentinel}"', depends_on=['a', 'b'], readiness=ReadinessCheck('process', '', .8))
            session = WorkspaceSession('session', 'Parallel failures', ['c'])
            state = WorkspaceState([project], project.id, services=[a, b, c], sessions=[session])
            controller = ResilientSessionController(state, session, RuntimeSettings())
            controller.start()
            try:
                self.assertTrue(wait_until(lambda: {'a', 'b', 'c'}.issubset(controller.failed), timeout=4))
                self.assertIn(controller.status, {'DEGRADED', 'FAILED'})
                self.assertFalse(sentinel.exists())
                self.assertNotIn('c', controller.processes)
            finally:
                controller.stop()

    def test_managed_process_stop_terminates_spawned_child_tree(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            child = root / 'child.py'
            child.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
            parent = root / 'parent.py'
            parent.write_text(
                'from pathlib import Path\nimport subprocess,sys,time\n'
                'p=subprocess.Popen([sys.executable, sys.argv[2]])\n'
                'Path(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(30)\n',
                encoding='utf-8',
            )
            pid_file = root / 'child.pid'
            project = new_project(root, 'Process tree')
            managed = ManagedProcess(RunConfig('tree', 'Tree', f'"{sys.executable}" "{parent}" "{pid_file}" "{child}"'), project)
            managed.start()
            child_pid = None
            try:
                self.assertTrue(wait_until(pid_file.exists, timeout=4))
                child_pid = int(pid_file.read_text(encoding='utf-8'))
                self.assertTrue(pid_alive(child_pid))
                managed.stop(grace=.6)
                self.assertTrue(wait_until(lambda: not managed.running, timeout=3))
                self.assertTrue(wait_until(lambda: not pid_alive(child_pid), timeout=5))
            finally:
                managed.stop(grace=.2)
                if child_pid and pid_alive(child_pid):
                    terminate_pid_tree(child_pid, timeout=.5)


if __name__ == '__main__':
    unittest.main()
