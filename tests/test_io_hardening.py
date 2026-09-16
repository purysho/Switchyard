import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from switchyard_core import Project, WorkspaceState, load_state, save_state
from switchyard_logs import LogStore
from switchyard_persistence import backup_path


class IOHardeningTests(unittest.TestCase):
    def test_concurrent_state_saves_remain_atomic_and_schema_valid(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            states = [
                WorkspaceState([Project(f'p{i}', f'Project {i}', d)], selected_project=f'p{i}')
                for i in range(24)
            ]

            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(save_state, state, path) for state in states]
                for future in futures:
                    future.result(timeout=5)

            loaded = load_state(path)
            self.assertIn(loaded.projects[0].name, {f'Project {i}' for i in range(24)})
            canonical = json.loads(path.read_text(encoding='utf-8'))
            self.assertIsInstance(canonical.get('projects'), list)
            for index in range(1, 4):
                backup = backup_path(path, index)
                if backup.exists():
                    raw = json.loads(backup.read_text(encoding='utf-8'))
                    self.assertIsInstance(raw.get('projects'), list)
            self.assertEqual(list(Path(d).glob('.state.json.*.tmp')), [])

    def test_stale_crash_temp_file_never_overrides_canonical_state(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            expected = WorkspaceState([Project('safe', 'Canonical', d)], selected_project='safe')
            save_state(expected, path)
            (Path(d) / '.state.json.interrupted.tmp').write_text('{half-written', encoding='utf-8')

            loaded = load_state(path)
            self.assertEqual(loaded.selected_project, 'safe')
            self.assertEqual(loaded.projects[0].name, 'Canonical')

    def test_concurrent_log_json_exports_are_never_partially_written(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'logs.json'
            store = LogStore(max_entries=2000, max_per_service=2000)
            for index in range(750):
                store.add('svc', 'Service', 'Project', f'line {index}')

            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(store.export_json, output) for _ in range(20)]
                for future in futures:
                    future.result(timeout=5)

            payload = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(len(payload), 750)
            self.assertEqual(payload[-1]['line'], 'line 749')
            self.assertEqual(list(Path(d).glob('.logs.json.*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
