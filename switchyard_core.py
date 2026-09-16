from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable
import json, os, shlex, socket, subprocess, threading, time, uuid

STATE_DIR = Path.home()/'.switchyard'
STATE_FILE = STATE_DIR/'state.json'

@dataclass
class RunConfig:
    id: str
    name: str
    command: str
    cwd: str | None = None
    env: dict[str,str] = field(default_factory=dict)

@dataclass
class Project:
    id: str
    name: str
    path: str
    notes: str = ''
    run_configs: list[RunConfig] = field(default_factory=list)

@dataclass
class WorkspaceState:
    projects: list[Project] = field(default_factory=list)
    selected_project: str | None = None


def _config_from_dict(d): return RunConfig(id=d.get('id') or uuid.uuid4().hex, name=d['name'], command=d['command'], cwd=d.get('cwd'), env=dict(d.get('env') or {}))
def _project_from_dict(d): return Project(id=d.get('id') or uuid.uuid4().hex, name=d['name'], path=d['path'], notes=d.get('notes',''), run_configs=[_config_from_dict(x) for x in d.get('run_configs',[])])

def load_state(path: Path=STATE_FILE) -> WorkspaceState:
    if not path.exists(): return WorkspaceState()
    data=json.loads(path.read_text(encoding='utf-8'))
    return WorkspaceState(projects=[_project_from_dict(x) for x in data.get('projects',[])], selected_project=data.get('selected_project'))

def save_state(state: WorkspaceState,path:Path=STATE_FILE):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(asdict(state),indent=2),encoding='utf-8'); tmp.replace(path)

def new_project(path:str|Path,name:str|None=None)->Project:
    p=Path(path).expanduser().resolve(); return Project(uuid.uuid4().hex,name or p.name,str(p))

def project_snapshot(project:Project)->dict:
    p=Path(project.path); out={'exists':p.exists(),'git':False,'branch':'','dirty':None,'files':0,'bytes':0,'run_configs':len(project.run_configs)}
    if not p.is_dir(): return out
    for base,dirs,files in os.walk(p):
        dirs[:]=[d for d in dirs if d not in {'.git','node_modules','.venv','__pycache__'}]
        for n in files:
            q=Path(base)/n
            try: st=q.stat(); out['files']+=1; out['bytes']+=st.st_size
            except OSError: pass
    if (p/'.git').exists():
        out['git']=True
        try:
            out['branch']=subprocess.run(['git','-C',str(p),'branch','--show-current'],capture_output=True,text=True,timeout=3).stdout.strip()
            status=subprocess.run(['git','-C',str(p),'status','--porcelain'],capture_output=True,text=True,timeout=3).stdout
            out['dirty']=bool(status.strip())
        except Exception: pass
    return out


def check_port(host:str,port:int,timeout:float=.25)->bool:
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
        s.settimeout(timeout); return s.connect_ex((host,port))==0

def scan_local_ports(ports:Iterable[int],host:str='127.0.0.1')->list[int]: return [p for p in ports if check_port(host,p)]

class ManagedProcess:
    def __init__(self, config:RunConfig, project:Project):
        self.config=config; self.project=project; self.process:subprocess.Popen|None=None; self.started_at:float|None=None; self.lines:list[str]=[]; self.returncode:int|None=None; self._thread=None
    def start(self,on_line=None,on_exit=None):
        if self.process and self.process.poll() is None: raise RuntimeError('Process already running')
        cwd=self.config.cwd or self.project.path; env=os.environ.copy(); env.update(self.config.env)
        self.process=subprocess.Popen(self.config.command,cwd=cwd,env=env,shell=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
        self.started_at=time.time(); self._thread=threading.Thread(target=self._pump,args=(on_line,on_exit),daemon=True); self._thread.start(); return self.process.pid
    def _pump(self,on_line,on_exit):
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            text=line.rstrip('\n'); self.lines.append(text)
            if on_line: on_line(text)
        self.returncode=self.process.wait()
        try: self.process.stdout.close()
        except Exception: pass
        if on_exit: on_exit(self.returncode)
    def stop(self,grace:float=2.0):
        if not self.process or self.process.poll() is not None:return
        self.process.terminate()
        try:self.process.wait(timeout=grace)
        except subprocess.TimeoutExpired:self.process.kill()
    @property
    def running(self): return bool(self.process and self.process.poll() is None)