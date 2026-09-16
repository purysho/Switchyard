import tempfile
import unittest
from pathlib import Path

from switchyard_core import Project, ReadinessCheck, Service, WorkspaceSession, WorkspaceState
from switchyard_daily_model import PaletteItem, dashboard_summary, rank_palette


class DailyDriverTests(unittest.TestCase):
    def test_palette_ranking_filters_tokens(self):
        items = [
            PaletteItem('a','Start session · Development','Start workspace',('session','dev')),
            PaletteItem('b','Handoff · Relay','Inspect endpoint',('http','api')),
            PaletteItem('c','Open project · Threadline','Local project',('project',)),
        ]
        self.assertEqual(rank_palette(items,'relay')[0].id,'b')
        self.assertEqual(rank_palette(items,'start dev')[0].id,'a')
        self.assertEqual(rank_palette(items,'no such command'),[])

    def test_dashboard_surfaces_missing_and_port_conflicts(self):
        with tempfile.TemporaryDirectory() as d:
            existing = Project('p1','Existing',d,pinned=True,last_opened=20)
            missing = Project('p2','Missing',str(Path(d)/'nope'),last_opened=10)
            a = Service('a','p1','API','api',readiness=ReadinessCheck('port','8000'))
            b = Service('b','p1','Worker','worker',readiness=ReadinessCheck('port','8000'))
            state = WorkspaceState([missing,existing],services=[a,b],sessions=[WorkspaceSession('s','Dev',['a','b'])])
            summary = dashboard_summary(state, {'s':'RUNNING'}, {'a':'READY','b':'STARTING'})
            self.assertEqual(summary.projects[0].name,'Existing')
            self.assertEqual(summary.missing_count,1)
            self.assertEqual(summary.running_sessions,1)
            self.assertEqual(summary.ready_services,1)
            self.assertEqual(len(summary.port_conflicts),1)
            self.assertTrue(any('Missing' in line for line in summary.attention))
            self.assertTrue(any('Port conflict' in line for line in summary.attention))


if __name__ == '__main__':
    unittest.main()
