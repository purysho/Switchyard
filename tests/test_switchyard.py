import tempfile, unittest, sys, time
from pathlib import Path
from switchyard_core import *
class SwitchyardTests(unittest.TestCase):
    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            sf=Path(d)/'state.json';p=new_project(d,'Demo');p.run_configs.append(RunConfig('x','Echo',f'"{sys.executable}" -c "print(123)"'));s=WorkspaceState([p],p.id);save_state(s,sf);r=load_state(sf);self.assertEqual(r.projects[0].name,'Demo');self.assertEqual(r.projects[0].run_configs[0].name,'Echo')
    def test_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'x.txt').write_bytes(b'abc');s=project_snapshot(new_project(p));self.assertEqual(s['files'],1);self.assertEqual(s['bytes'],3)
    def test_managed_process(self):
        with tempfile.TemporaryDirectory() as d:
            p=new_project(d);c=RunConfig('x','test',f'"{sys.executable}" -c "print(\'ok\')"');m=ManagedProcess(c,p);m.start();
            for _ in range(100):
                if not m.running:break
                time.sleep(.01)
            self.assertEqual(m.returncode,0);self.assertIn('ok',m.lines)
if __name__=='__main__':unittest.main()