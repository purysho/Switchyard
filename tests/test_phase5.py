import json
import os
import tempfile
import unittest
from pathlib import Path

from switchyard_core import Project, ReadinessCheck, Service, WorkspaceSession, WorkspaceState
from switchyard_logs import LogStore, infer_level
from switchyard_topology import (
    begin_recovery_journal,
    clean_recovery_journal,
    import_session_snapshot,
    import_session_template,
    load_session_snapshot,
    pid_alive,
    port_claims,
    recovery_processes,
    save_session_snapshot,
    session_template,
    topology_layout,
    update_recovery_journal,
)


class Phase5Tests(unittest.TestCase):
    def _state(self):
        p1 = Project('p1', 'API Project', '.')
        p2 = Project('p2', 'Web Project', '.')
        db = Service('db', 'p1', 'DATABASE', 'db', readiness=ReadinessCheck('port', '5432', 5))
        api = Service('api', 'p1', 'API', 'api', depends_on=['db'], readiness=ReadinessCheck('http', 'http://127.0.0.1:8000/health', 5))
        web = Service('web', 'p2', 'WEB', 'web', depends_on=['api'], readiness=ReadinessCheck('port', '5173', 5))
        session = WorkspaceSession('s', 'Development', ['web'])
        return WorkspaceState([p1, p2], services=[db, api, web], sessions=[session]), session

    def test_topology_is_dependency_layered(self):
        state, session = self._state()
        nodes, edges = topology_layout(state.services, session.service_ids)
        depth = {node.service_id: node.depth for node in nodes}
        self.assertLess(depth['db'], depth['api'])
        self.assertLess(depth['api'], depth['web'])
        self.assertEqual({(e.source_id, e.target_id) for e in edges}, {('db', 'api'), ('api', 'web')})

    def test_port_conflicts_are_explicit(self):
        a = Service('a', 'p', 'A', 'a', readiness=ReadinessCheck('port', '8000'))
        b = Service('b', 'p', 'B', 'b', readiness=ReadinessCheck('port', '8000'))
        claims = port_claims([a, b])
        self.assertEqual(len(claims), 1)
        self.assertTrue(claims[0].conflict)
        self.assertEqual(set(claims[0].service_ids), {'a', 'b'})

    def test_log_store_filters_and_bounds(self):
        store = LogStore(max_entries=100, max_per_service=100)
        store.add('a', 'API', 'Demo', 'server started')
        store.add('a', 'API', 'Demo', 'warning: deprecated option')
        store.add('b', 'WEB', 'Demo', 'ERROR: build failed')
        self.assertEqual(infer_level('ERROR: bad'), 'ERROR')
        self.assertEqual(len(store.query(service_id='a')), 2)
        self.assertEqual(len(store.query(text='failed')), 1)
        self.assertEqual(store.query(levels=['WARN'])[0].level, 'WARN')

    def test_template_mapping_and_snapshot_roundtrip(self):
        state, session = self._state()
        template = session_template(state, session)
        target = WorkspaceState([Project('x1', 'Backend', '.'), Project('x2', 'Frontend', '.')])
        mapping = {'API Project': 'x1', 'Web Project': 'x2'}
        imported_session, imported_services = import_session_template(target, template, mapping)
        self.assertEqual(imported_session.name, 'Development')
        self.assertEqual(len(imported_services), 3)
        self.assertEqual({s.project_id for s in imported_services}, {'x1', 'x2'})

        with tempfile.TemporaryDirectory() as d:
            path = save_session_snapshot(state, session, {'session_profile': 'local'}, directory=d)
            snap = load_session_snapshot(path)
            restored_session, restored_services, metadata = import_session_snapshot(target, snap, mapping)
            self.assertTrue(restored_session.name.startswith('Development'))
            self.assertEqual(len(restored_services), 3)
            self.assertEqual(metadata['session_profile'], 'local')
            raw = path.read_text(encoding='utf-8')
            self.assertNotIn('SECRET=', raw)

    def test_recovery_journal_tracks_process_liveness(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recovery.json'
            self.assertIsNone(begin_recovery_journal(path))
            session = WorkspaceSession('s', 'Dev', [])
            update_recovery_journal(session, {'svc': os.getpid()}, path)
            previous = begin_recovery_journal(path)
            rows = recovery_processes(previous)
            self.assertEqual(rows[0].service_id, 'svc')
            self.assertTrue(rows[0].alive)
            self.assertTrue(pid_alive(os.getpid()))
            clean_recovery_journal(path)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
