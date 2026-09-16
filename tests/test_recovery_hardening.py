import os
import tempfile
import unittest
from pathlib import Path

from switchyard_core import WorkspaceSession
from switchyard_topology import (
    acknowledge_recovery_journal,
    begin_recovery_journal,
    clean_recovery_journal,
    recovery_marker,
    update_recovery_journal,
)


class RecoveryJournalHardeningTests(unittest.TestCase):
    def test_unresolved_recovery_survives_a_second_switchyard_crash(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recovery.json'
            self.assertIsNone(begin_recovery_journal(path))

            crashed_session = WorkspaceSession('old-session', 'Previous development', [])
            update_recovery_journal(crashed_session, {'api': 2147483647}, path)

            first_restart = begin_recovery_journal(path)
            self.assertEqual(first_restart['active_session_id'], 'old-session')
            self.assertEqual(first_restart['processes'], {'api': 2147483647})
            armed = recovery_marker(path)
            self.assertIsNone(armed['active_session_id'])
            self.assertEqual(armed['pending_recovery']['active_session_id'], 'old-session')

            # Simulate Switchyard itself crashing before the recovery dialog is resolved.
            second_restart = begin_recovery_journal(path)
            self.assertEqual(second_restart['active_session_id'], 'old-session')
            self.assertEqual(second_restart['processes'], {'api': 2147483647})
            self.assertEqual(recovery_marker(path)['pending_recovery']['processes'], {'api': 2147483647})

            clean_recovery_journal(path)

    def test_regular_journal_updates_do_not_erase_pending_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recovery.json'
            begin_recovery_journal(path)
            update_recovery_journal(WorkspaceSession('old', 'Old', []), {'svc': 2147483647}, path)
            previous = begin_recovery_journal(path)
            self.assertEqual(previous['active_session_id'], 'old')

            # The fresh process may start/stop other sessions while the user has not yet
            # resolved the previous crash. Those updates must preserve pending_recovery.
            update_recovery_journal(WorkspaceSession('new', 'New', []), {'new-svc': os.getpid()}, path)
            marker = recovery_marker(path)
            self.assertEqual(marker['active_session_id'], 'new')
            self.assertEqual(marker['pending_recovery']['active_session_id'], 'old')
            self.assertEqual(marker['pending_recovery']['processes'], {'svc': 2147483647})

            clean_recovery_journal(path)

    def test_acknowledgement_forgets_pending_recovery_but_keeps_current_run_armed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recovery.json'
            begin_recovery_journal(path)
            update_recovery_journal(WorkspaceSession('old', 'Old', []), {'svc': 2147483647}, path)
            begin_recovery_journal(path)

            acknowledge_recovery_journal(path)
            marker = recovery_marker(path)
            self.assertIsNone(marker['pending_recovery'])
            self.assertEqual(marker['pid'], os.getpid())
            self.assertIsNone(marker['active_session_id'])

            # A cleanly acknowledged prior crash must not be offered again.
            self.assertIsNone(begin_recovery_journal(path))
            clean_recovery_journal(path)


if __name__ == '__main__':
    unittest.main()
