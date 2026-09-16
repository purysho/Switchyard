import json
import tempfile
import unittest
from pathlib import Path

from switchyard_core import Project, WorkspaceState, load_state, save_state, state_recovery_notice
from switchyard_persistence import backup_path


class BackupChainHardeningTests(unittest.TestCase):
    def tearDown(self):
        state_recovery_notice(clear=True)

    def test_recovery_skips_damaged_newest_backup_and_uses_older_generation(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            for index in range(1, 4):
                save_state(
                    WorkspaceState([Project(f'p{index}', f'Generation {index}', d)], selected_project=f'p{index}'),
                    path,
                )

            # Current = generation 3, bak1 = generation 2, bak2 = generation 1.
            path.write_text('{broken current', encoding='utf-8')
            backup_path(path, 1).write_text('{broken newest backup', encoding='utf-8')

            recovered = load_state(path)
            notice = state_recovery_notice()

            self.assertEqual(recovered.projects[0].name, 'Generation 1')
            self.assertEqual(recovered.selected_project, 'p1')
            self.assertIsNotNone(notice)
            self.assertIn(backup_path(path, 2).name, notice.message)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['projects'][0]['name'], 'Generation 1')


if __name__ == '__main__':
    unittest.main()
