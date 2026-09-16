import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from switchyard_core import (
    ManagedProcess,
    Project,
    ReadinessCheck,
    RunConfig,
    Service,
    WorkspaceSession,
    WorkspaceState,
    load_state,
    new_project,
    save_state,
    state_recovery_notice,
)
from switchyard_persistence import (
    FutureSchemaError,
    atomic_write_json,
    backup_path,
)
from switchyard_runtime import (
    EnvironmentProfile,
    ResilientSessionController,
    RuntimeSettings,
    ServiceRuntimePolicy,
    load_runtime,
    runtime_recovery_notice,
    save_runtime,
)
from switchyard_topology import (
    begin_recovery_journal,
    clean_recovery_journal,
    recovery_marker,
    recovery_processes,
    update_recovery_journal,
)


def wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


class PersistenceHardeningTests(unittest.TestCase):
    def tearDown(self):
        state_recovery_notice(clear=True)
        runtime_recovery_notice(clear=True)

    def test_corrupt_state_recovers_previous_valid_backup_and_archives_damage(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            first = WorkspaceState([Project('p1', 'Before corruption', d)], selected_project='p1')
            second = WorkspaceState([Project('p2', 'Latest', d)], selected_project='p2')
            save_state(first, path)
            save_state(second, path)
            self.assertTrue(backup_path(path, 1).exists())

            path.write_text('{ definitely not json', encoding='utf-8')
            recovered = load_state(path)
            notice = state_recovery_notice()

            self.assertEqual(recovered.projects[0].name, 'Before corruption')
            self.assertEqual(recovered.selected_project, 'p1')
            self.assertIsNotNone(notice)
            self.assertIn('recovered from backup', notice.message)
            self.assertTrue(notice.archived and Path(notice.archived).exists())
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['projects'][0]['name'], 'Before corruption')

    def test_structurally_invalid_state_is_not_promoted_to_backup(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            valid = WorkspaceState([Project('p', 'Valid', d)], selected_project='p')
            save_state(valid, path)
            shutil.copy2(path, backup_path(path, 1))
            path.write_text(json.dumps({'version': 3, 'projects': 'not-a-list'}), encoding='utf-8')

            recovered = load_state(path)
            self.assertEqual(recovered.projects[0].name, 'Valid')
            self.assertIsInstance(json.loads(backup_path(path, 1).read_text(encoding='utf-8'))['projects'], list)

    def test_unrecoverable_corrupt_state_fails_closed_to_defaults_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            path.write_bytes(b'\x00\xffbroken-json')
            state = load_state(path)
            notice = state_recovery_notice()

            self.assertEqual(state.projects, [])
            self.assertIsNotNone(notice)
            self.assertIn('safe defaults', notice.message)
            self.assertFalse(path.exists())
            self.assertTrue(notice.archived and Path(notice.archived).exists())

    def test_future_state_schema_is_never_overwritten_by_save(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            future = {'version': 999, 'projects': [], 'sentinel': 'do-not-destroy'}
            original = json.dumps(future, indent=2)
            path.write_text(original, encoding='utf-8')

            with self.assertRaises(FutureSchemaError):
                save_state(WorkspaceState(), path)

            self.assertEqual(path.read_text(encoding='utf-8'), original)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['sentinel'], 'do-not-destroy')

    def test_future_state_can_recover_from_supported_backup_without_losing_future_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            supported = WorkspaceState([Project('p', 'Supported backup', d)], selected_project='p')
            save_state(supported, path)
            shutil.copy2(path, backup_path(path, 1))
            path.write_text(json.dumps({'version': 999, 'projects': [], 'future': True}), encoding='utf-8')

            recovered = load_state(path)
            notice = state_recovery_notice()

            self.assertEqual(recovered.projects[0].name, 'Supported backup')
            self.assertIsNotNone(notice)
            self.assertTrue(notice.archived and Path(notice.archived).exists())
            archived = json.loads(Path(notice.archived).read_text(encoding='utf-8'))
            self.assertEqual(archived['version'], 999)
            self.assertTrue(archived['future'])

    def test_atomic_replace_failure_leaves_existing_canonical_file_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            original = {'version': 3, 'sentinel': 'original'}
            atomic_write_json(path, original)

            with mock.patch('switchyard_persistence.os.replace', side_effect=OSError('simulated power loss')):
                with self.assertRaises(OSError):
                    atomic_write_json(path, {'version': 3, 'sentinel': 'replacement'})

            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), original)

    def test_backup_rotation_keeps_three_distinct_previous_generations(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            for index in range(1, 5):
                save_state(WorkspaceState([Project(f'p{index}', f'Generation {index}', d)]), path)

            self.assertEqual(json.loads(backup_path(path, 1).read_text(encoding='utf-8'))['projects'][0]['name'], 'Generation 3')
            self.assertEqual(json.loads(backup_path(path, 2).read_text(encoding='utf-8'))['projects'][0]['name'], 'Generation 2')
            self.assertEqual(json.loads(backup_path(path, 3).read_text(encoding='utf-8'))['projects'][0]['name'], 'Generation 1')

    def test_runtime_corruption_recovers_profile_without_materializing_inherited_secret(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'runtime.json'
            first = RuntimeSettings(profiles=[EnvironmentProfile('local', 'Local', {'MODE': 'dev'}, ['TOKEN'])])
            second = RuntimeSettings(profiles=[EnvironmentProfile('other', 'Other', {'MODE': 'test'}, ['TOKEN'])])
            save_runtime(first, path)
            save_runtime(second, path)
            path.write_text('{bad runtime', encoding='utf-8')

            recovered = load_runtime(path)
            notice = runtime_recovery_notice()
            raw = path.read_text(encoding='utf-8')

            self.assertEqual(recovered.profiles[0].name, 'Local')
            self.assertIn('TOKEN', raw)
            self.assertNotIn('secret-value', raw)
            self.assertIsNotNone(notice)
            self.assertIn('recovered from backup', notice.message)

    def test_unicode_and_space_heavy_project_paths_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / '项目 with spaces – café'
            root.mkdir()
            project = new_project(root, 'Unicode 项目')
            project.notes = 'Notes: 日本語 · café · ✓'
            project.tags = ['local first', '测试']
            path = Path(d) / 'state file.json'

            save_state(WorkspaceState([project], project.id), path)
            loaded = load_state(path)

            self.assertEqual(Path(loaded.projects[0].path), root.resolve())
            self.assertEqual(loaded.projects[0].name, 'Unicode 项目')
            self.assertEqual(loaded.projects[0].notes, project.notes)
            self.assertEqual(loaded.projects[0].tags, project.tags)


class CrashHardeningTests(unittest.TestCase):
    def test_stale_crash_journal_marks_dead_pid_and_rearms_current_run(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recovery.json'
            stale_pid = 2147483647
            path.write_text(json.dumps({
                'version': 2,
                'pid': stale_pid,
                'active_session_id': 'old',
                'active_session_name': 'Old session',
                'processes': {'svc': stale_pid},
            }), encoding='utf-8')

            previous = begin_recovery_journal(path)
            rows = recovery_processes(previous)
            current = recovery_marker(path)

            self.assertEqual(previous['active_session_id'], 'old')
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0].alive)
            self.assertEqual(current['pid'], os.getpid())
            self.assertIsNone(current['active_session_id'])
            clean_recovery_journal(path)

    def test_recovery_journal_tracks_real_child_then_observes_it_dead(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recovery.json'
            project = new_project(d, 'Crash test')
            config = RunConfig('run', 'Sleeper', f'"{sys.executable}" -c "import time;time.sleep(10)"')
            managed = ManagedProcess(config, project)
            pid = managed.start()
            try:
                begin_recovery_journal(path)
                session = WorkspaceSession('s', 'Crash simulation', [])
                update_recovery_journal(session, {'svc': pid}, path)
                before = recovery_processes(recovery_marker(path))
                self.assertTrue(before[0].alive)
                managed.stop(grace=.2)
                self.assertTrue(wait_until(lambda: managed.returncode is not None, timeout=3))
                after = recovery_processes(recovery_marker(path))
                self.assertFalse(after[0].alive)
            finally:
                managed.stop(grace=.1)
                clean_recovery_journal(path)

    def test_managed_process_output_is_bounded_under_log_flood(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / '日志 flood with spaces'
            root.mkdir()
            script = root / 'emit_many.py'
            script.write_text('for i in range(6200):\n print(f"line-{i}", flush=True)\n', encoding='utf-8')
            project = new_project(root)
            config = RunConfig('flood', 'Flood', f'"{sys.executable}" "{script}"')
            managed = ManagedProcess(config, project)
            managed.start()

            self.assertTrue(wait_until(lambda: managed.returncode is not None, timeout=12))
            self.assertEqual(managed.returncode, 0)
            self.assertLessEqual(len(managed.lines), 5000)
            self.assertEqual(managed.lines[-1], 'line-6199')
            self.assertNotIn('line-0', managed.lines)

    def test_restart_loop_is_strictly_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Crash loop')
            script = Path(d) / 'always_fail.py'
            script.write_text('import sys\nsys.exit(9)\n', encoding='utf-8')
            command = f'"{sys.executable}" "{script}"'
            service = Service(
                'svc', project.id, 'Always fails', command,
                readiness=ReadinessCheck('process', '', .5),
                failure_policy='continue',
            )
            session = WorkspaceSession('session', 'Crash loop', ['svc'])
            state = WorkspaceState([project], project.id, services=[service], sessions=[session])
            settings = RuntimeSettings(policies=[ServiceRuntimePolicy('svc', 'on_failure', 2, .01, .02)])
            controller = ResilientSessionController(state, session, settings)
            controller.start()
            try:
                self.assertTrue(wait_until(
                    lambda: controller.restart_counts.get('svc', 0) >= 2 and not controller._restarting,
                    timeout=5,
                ))
                time.sleep(.15)
                self.assertEqual(controller.restart_counts.get('svc'), 2)
                self.assertLessEqual(sum(e.kind == 'restart' for e in state.session_history), 2)
                self.assertIn(controller.status, {'DEGRADED', 'FAILED'})
                proc = controller.processes.get('svc')
                self.assertTrue(proc is None or not proc.running)
            finally:
                controller.stop()

    def test_failed_dependency_blocks_dependent_service_from_starting(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(d, 'Dependency crash')
            fail_script = Path(d) / 'fail.py'
            fail_script.write_text('import sys\nsys.exit(23)\n', encoding='utf-8')
            long_script = Path(d) / 'long.py'
            long_script.write_text('import time\ntime.sleep(5)\n', encoding='utf-8')
            first = Service(
                'first', project.id, 'Database', f'"{sys.executable}" "{fail_script}"',
                readiness=ReadinessCheck('process', '', .4), failure_policy='stop_dependents',
            )
            second = Service(
                'second', project.id, 'API', f'"{sys.executable}" "{long_script}"',
                depends_on=['first'], readiness=ReadinessCheck('process', '', .4),
            )
            session = WorkspaceSession('s', 'Broken dependency', ['second'])
            state = WorkspaceState([project], project.id, services=[first, second], sessions=[session])
            controller = ResilientSessionController(state, session, RuntimeSettings())
            controller.start()
            try:
                self.assertTrue(wait_until(lambda: controller.status in {'DEGRADED', 'FAILED'}, timeout=4))
                self.assertIn('first', controller.failed)
                self.assertIn('second', controller.failed)
                self.assertNotIn('second', controller.processes)
                self.assertTrue(any(e.kind == 'blocked' and e.service_id == 'second' for e in state.session_history))
            finally:
                controller.stop()


if __name__ == '__main__':
    unittest.main()
