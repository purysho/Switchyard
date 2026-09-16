import json
import tempfile
import unittest
import sys
import time
from pathlib import Path
from switchyard_core import *


class SwitchyardTests(unittest.TestCase):
    def test_state_roundtrip_and_v1_migration(self):
        with tempfile.TemporaryDirectory() as d:
            sf = Path(d) / 'state.json'
            p = new_project(d, 'Demo')
            p.tags = ['work']
            p.pinned = True
            p.run_configs.append(RunConfig('x', 'Echo', f'"{sys.executable}" -c "print(123)"'))
            rec = RunRecord('r', p.id, p.name, 'x', 'Echo', 'echo', 1.0, 2.0, 0, 123)
            s = WorkspaceState([p], p.id, [rec])
            save_state(s, sf)
            r = load_state(sf)
            self.assertEqual(r.version, STATE_VERSION)
            self.assertEqual(r.projects[0].tags, ['work'])
            self.assertTrue(r.projects[0].pinned)
            self.assertEqual(r.run_history[0].returncode, 0)

            sf.write_text(json.dumps({'projects': [{'name': 'Old', 'path': d}], 'selected_project': None}), encoding='utf-8')
            migrated = load_state(sf)
            self.assertEqual(migrated.projects[0].name, 'Old')
            self.assertEqual(migrated.version, STATE_VERSION)

    def test_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'x.txt').write_bytes(b'abc')
            s = project_snapshot(new_project(p))
            self.assertEqual(s['files'], 1)
            self.assertEqual(s['bytes'], 3)

    def test_detect_node_and_python(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'package.json').write_text(json.dumps({'scripts': {'dev': 'vite', 'test': 'vitest'}, 'dependencies': {'react': '1'}}))
            (p / 'main.py').write_text('print(1)')
            (p / 'tests').mkdir()
            result = detect_project(p)
            self.assertIn('Node.js', result['stacks'])
            self.assertIn('React', result['stacks'])
            self.assertIn('Python', result['stacks'])
            commands = [x['command'] for x in result['tasks']]
            self.assertIn('npm run dev', commands)
            self.assertIn('python -m unittest discover -s tests -v', commands)

    def test_suggested_configs_skip_existing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'package.json').write_text(json.dumps({'scripts': {'dev': 'vite', 'build': 'vite build'}}))
            project = new_project(p)
            project.run_configs.append(RunConfig('x', 'Dev', 'npm run dev'))
            commands = [x.command for x in suggested_run_configs(project)]
            self.assertNotIn('npm run dev', commands)
            self.assertIn('npm run build', commands)

    def test_health_missing_project(self):
        with tempfile.TemporaryDirectory() as d:
            project = new_project(Path(d) / 'missing')
            checks = project_health(project)
            self.assertFalse(checks[0]['ok'])

    def test_managed_process(self):
        with tempfile.TemporaryDirectory() as d:
            p = new_project(d)
            c = RunConfig('x', 'test', f'"{sys.executable}" -c "print(\'ok\')"')
            m = ManagedProcess(c, p)
            m.start()
            for _ in range(200):
                if not m.running:
                    break
                time.sleep(.01)
            self.assertEqual(m.returncode, 0)
            self.assertIn('ok', m.lines)
            self.assertIsNotNone(m.ended_at)


if __name__ == '__main__':
    unittest.main()
