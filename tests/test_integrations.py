import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from switchyard_core import ReadinessCheck, Service
from switchyard_integrations import discover_tool, handoff_args, readiness_url


class IntegrationTests(unittest.TestCase):
    def test_discovers_sibling_source_tool(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project = root / 'Demo'; project.mkdir()
            relay = root / 'Relay'; relay.mkdir(); (relay / 'relay_desktop.pyw').write_text('# test', encoding='utf-8')
            found = discover_tool('relay', [str(project)], extra_roots=[])
            self.assertIsNotNone(found)
            self.assertEqual(found.mode, 'source')
            self.assertTrue(found.location.endswith('relay_desktop.pyw'))

    def test_environment_override_has_priority(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / 'BLACKBOX.exe'; exe.write_bytes(b'fake')
            with mock.patch.dict(os.environ, {'PURYSHO_BLACKBOX_PATH': str(exe)}):
                found = discover_tool('blackbox', [])
            self.assertIsNotNone(found)
            self.assertEqual(found.mode, 'executable')
            self.assertEqual(Path(found.location), exe)

    def test_service_readiness_handoffs(self):
        http = Service('a','p','API','api',readiness=ReadinessCheck('http','http://127.0.0.1:8000/health'))
        port = Service('b','p','WEB','web',readiness=ReadinessCheck('port','5173',host='127.0.0.1'))
        self.assertEqual(readiness_url(http.readiness), 'http://127.0.0.1:8000/health')
        self.assertEqual(readiness_url(port.readiness), 'http://127.0.0.1:5173/')
        self.assertEqual(handoff_args('relay', service=http), ['--url','http://127.0.0.1:8000/health'])
        self.assertEqual(handoff_args('pulse', pid=1234), ['--pid','1234'])
        self.assertEqual(handoff_args('blackbox', project_path='/tmp/demo'), ['--repo','/tmp/demo'])
        self.assertEqual(handoff_args('needle', project_path='/tmp/demo', query='TODO'), ['--root','/tmp/demo','--query','TODO'])


if __name__ == '__main__':
    unittest.main()
