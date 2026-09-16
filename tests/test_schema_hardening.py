import json
import tempfile
import unittest
from pathlib import Path

from switchyard_core import (
    Project,
    RunRecord,
    SessionEvent,
    WorkspaceState,
    load_state,
    save_state,
    state_recovery_notice,
)
from switchyard_persistence import FutureSchemaError
from switchyard_runtime import (
    RuntimeSettings,
    load_runtime,
    runtime_recovery_notice,
    save_runtime,
)


class SchemaHardeningTests(unittest.TestCase):
    def tearDown(self):
        state_recovery_notice(clear=True)
        runtime_recovery_notice(clear=True)

    def test_string_project_tags_are_rejected_instead_of_split_into_characters(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            path.write_text(json.dumps({
                'version': 3,
                'projects': [{
                    'id': 'p',
                    'name': 'Malformed',
                    'path': d,
                    'tags': 'not-a-list',
                    'run_configs': [],
                }],
            }), encoding='utf-8')

            state = load_state(path)
            notice = state_recovery_notice()
            self.assertEqual(state.projects, [])
            self.assertIsNotNone(notice)
            self.assertIn('project.tags must be a list of strings', notice.message)
            self.assertTrue(notice.archived and Path(notice.archived).exists())

    def test_string_service_ids_are_rejected_instead_of_split_into_characters(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            path.write_text(json.dumps({
                'version': 3,
                'projects': [],
                'sessions': [{
                    'id': 'session',
                    'name': 'Malformed session',
                    'service_ids': 'api',
                }],
            }), encoding='utf-8')

            state = load_state(path)
            notice = state_recovery_notice()
            self.assertEqual(state.sessions, [])
            self.assertIsNotNone(notice)
            self.assertIn('session.service_ids must be a list of strings', notice.message)

    def test_string_runtime_inherit_keys_are_rejected_instead_of_split(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'runtime.json'
            path.write_text(json.dumps({
                'version': 1,
                'profiles': [{
                    'id': 'profile',
                    'name': 'Malformed',
                    'variables': {},
                    'inherit_keys': 'TOKEN',
                }],
                'policies': [],
                'session_profiles': {},
            }), encoding='utf-8')

            runtime = load_runtime(path)
            notice = runtime_recovery_notice()
            self.assertEqual(runtime.profiles, [])
            self.assertIsNotNone(notice)
            self.assertIn('profile.inherit_keys must be a list of strings', notice.message)

    def test_future_runtime_schema_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'runtime.json'
            original = json.dumps({'version': 999, 'sentinel': 'future-runtime'}, indent=2)
            path.write_text(original, encoding='utf-8')
            with self.assertRaises(FutureSchemaError):
                save_runtime(RuntimeSettings(), path)
            self.assertEqual(path.read_text(encoding='utf-8'), original)

    def test_persisted_histories_are_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            project = Project('p', 'Project', d)
            runs = [
                RunRecord(
                    f'r{i}', 'p', 'Project', f'c{i}', 'Config', 'echo test',
                    float(i), float(i + 1), 0, i,
                )
                for i in range(310)
            ]
            events = [
                SessionEvent(float(i), 'session', None, 'info', f'event {i}')
                for i in range(620)
            ]
            state = WorkspaceState([project], 'p', run_history=runs, session_history=events)
            save_state(state, path)
            loaded = load_state(path)

            self.assertEqual(len(state.run_history), 250)
            self.assertEqual(len(state.session_history), 500)
            self.assertEqual(len(loaded.run_history), 250)
            self.assertEqual(len(loaded.session_history), 500)
            self.assertEqual(loaded.run_history[0].id, 'r60')
            self.assertEqual(loaded.session_history[0].message, 'event 120')


if __name__ == '__main__':
    unittest.main()
