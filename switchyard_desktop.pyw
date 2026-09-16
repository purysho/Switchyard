from __future__ import annotations
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from pathlib import Path
import threading,time,uuid
from switchyard_core import *

BG='#090b0f';PANEL='#11161d';PANEL2='#171e27';TEXT='#f2efe7';MUTED='#8f99a6';GOLD='#d9a84e';CYAN='#5dbde7';GREEN='#7edb9b';RED='#ff776f'
def fmt(n):
    n=float(n)
    for u in ['B','KB','MB','GB']:
        if n<1024 or u=='GB':return f'{n:.1f} {u}'
        n/=1024
class SwitchyardApp(tk.Tk):
    def __init__(self):
        super().__init__();self.title('Switchyard — Local Developer Workspace');self.geometry('1380x860');self.minsize(1050,700);self.configure(bg=BG)
        self.state=load_state();self.managed:dict[str,ManagedProcess]={};self._style();self._build();self.refresh_projects();self.after(1000,self.tick)
    def _style(self):
        s=ttk.Style(self);s.theme_use('clam');s.configure('.',background=BG,foreground=TEXT,fieldbackground=PANEL);s.configure('TButton',background='#1d2630',foreground=TEXT,padding=8);s.map('TButton',background=[('active','#293745')]);s.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,rowheight=28);s.configure('Treeview.Heading',background=PANEL2,foreground=TEXT)
    def _build(self):
        top=tk.Frame(self,bg=BG);top.pack(fill='x',padx=18,pady=(14,8));tk.Label(top,text='SWITCHYARD',bg=BG,fg=TEXT,font=('Segoe UI Semibold',26)).pack(side='left');tk.Label(top,text='  local developer workspace command center',bg=BG,fg=MUTED).pack(side='left',pady=(10,0));ttk.Button(top,text='+ Add project',command=self.add_project).pack(side='right')
        main=tk.PanedWindow(self,orient='horizontal',bg='#202733',sashwidth=1);main.pack(fill='both',expand=True,padx=18,pady=(0,18))
        self.sidebar=tk.Frame(main,bg=PANEL,width=260);self.content=tk.Frame(main,bg=BG);main.add(self.sidebar,minsize=240);main.add(self.content,minsize=700)
        tk.Label(self.sidebar,text='PROJECTS',bg=PANEL,fg=GOLD,font=('Segoe UI Semibold',9)).pack(anchor='w',padx=14,pady=(14,8));self.project_list=tk.Listbox(self.sidebar,bg=PANEL,fg=TEXT,selectbackground='#273646',highlightthickness=0,borderwidth=0,font=('Segoe UI',11));self.project_list.pack(fill='both',expand=True,padx=8,pady=(0,8));self.project_list.bind('<<ListboxSelect>>',self.on_project);ttk.Button(self.sidebar,text='Remove selected',command=self.remove_project).pack(fill='x',padx=10,pady=10)
        self.header=tk.Frame(self.content,bg=BG);self.header.pack(fill='x',padx=18,pady=(8,12));self.project_title=tk.Label(self.header,text='Select a project',bg=BG,fg=TEXT,font=('Segoe UI Semibold',24));self.project_title.pack(anchor='w');self.project_meta=tk.Label(self.header,text='',bg=BG,fg=MUTED,font=('Consolas',10));self.project_meta.pack(anchor='w',pady=(4,0))
        nb=ttk.Notebook(self.content);nb.pack(fill='both',expand=True,padx=18,pady=(0,12));self.overview=tk.Frame(nb,bg=BG);self.runs=tk.Frame(nb,bg=BG);self.live=tk.Frame(nb,bg=BG);nb.add(self.overview,text='Overview');nb.add(self.runs,text='Run configurations');nb.add(self.live,text='Live processes')
        self._overview();self._runs();self._live()
    def _overview(self):
        self.cards=tk.Frame(self.overview,bg=BG);self.cards.pack(fill='x',pady=12);self.card_labels=[]
        for label in ['FILES','SIZE','GIT','BRANCH','PORTS']:
            f=tk.Frame(self.cards,bg=PANEL,highlightbackground='#222b35',highlightthickness=1);f.pack(side='left',fill='both',expand=True,padx=4);tk.Label(f,text=label,bg=PANEL,fg=MUTED,font=('Segoe UI Semibold',8)).pack(anchor='w',padx=12,pady=(10,2));v=tk.Label(f,text='—',bg=PANEL,fg=TEXT,font=('Segoe UI Semibold',17));v.pack(anchor='w',padx=12,pady=(0,12));self.card_labels.append(v)
        tk.Label(self.overview,text='NOTES',bg=BG,fg=GOLD,font=('Segoe UI Semibold',9)).pack(anchor='w',pady=(18,4));self.notes=tk.Text(self.overview,bg=PANEL,fg=TEXT,insertbackground=TEXT,height=10,relief='flat',wrap='word');self.notes.pack(fill='both',expand=True);self.notes.bind('<FocusOut>',lambda e:self.save_notes())
    def _runs(self):
        bar=tk.Frame(self.runs,bg=BG);bar.pack(fill='x',pady=10);ttk.Button(bar,text='+ Add run config',command=self.add_run).pack(side='left');ttk.Button(bar,text='Run selected',command=self.run_selected).pack(side='left',padx=8);ttk.Button(bar,text='Stop selected',command=self.stop_selected).pack(side='left')
        self.run_tree=ttk.Treeview(self.runs,columns=('name','command','state'),show='headings');
        for c,t,w in [('name','NAME',220),('command','COMMAND',600),('state','STATE',130)]:self.run_tree.heading(c,text=t);self.run_tree.column(c,width=w)
        self.run_tree.pack(fill='both',expand=True)
    def _live(self):
        self.live_tree=ttk.Treeview(self.live,columns=('project','config','pid','uptime','state'),show='headings');
        for c,t,w in [('project','PROJECT',180),('config','CONFIG',180),('pid','PID',90),('uptime','UPTIME',120),('state','STATE',120)]:self.live_tree.heading(c,text=t);self.live_tree.column(c,width=w)
        self.live_tree.pack(fill='x',pady=(10,8));tk.Label(self.live,text='OUTPUT',bg=BG,fg=GOLD,font=('Segoe UI Semibold',9)).pack(anchor='w');self.log=tk.Text(self.live,bg='#07090c',fg='#b7c5d3',insertbackground=TEXT,relief='flat',font=('Consolas',10));self.log.pack(fill='both',expand=True,pady=(4,0))
    def current(self):
        s=self.project_list.curselection();return self.state.projects[s[0]] if s else None
    def refresh_projects(self,select=None):
        self.project_list.delete(0,'end');
        for p in self.state.projects:self.project_list.insert('end',p.name)
        if self.state.projects:
            idx=0
            if select:
                idx=next((i for i,p in enumerate(self.state.projects) if p.id==select),0)
            self.project_list.selection_set(idx);self.project_list.event_generate('<<ListboxSelect>>')
    def add_project(self):
        p=filedialog.askdirectory();
        if not p:return
        proj=new_project(p);self.state.projects.append(proj);self.state.selected_project=proj.id;save_state(self.state);self.refresh_projects(proj.id)
    def remove_project(self):
        p=self.current();
        if not p:return
        if messagebox.askyesno('Switchyard',f'Remove {p.name} from Switchyard? Files will not be touched.'):
            self.state.projects=[x for x in self.state.projects if x.id!=p.id];save_state(self.state);self.refresh_projects()
    def on_project(self,_=None):
        p=self.current();
        if not p:return
        self.state.selected_project=p.id;save_state(self.state);self.project_title.config(text=p.name);self.project_meta.config(text=p.path);self.notes.delete('1.0','end');self.notes.insert('1.0',p.notes);self.refresh_snapshot(p);self.refresh_runs(p)
    def refresh_snapshot(self,p):
        def go():
            s=project_snapshot(p);ports=scan_local_ports([3000,4173,5173,8000,8080,1420,5000]);self.after(0,lambda:self.show_snapshot(s,ports))
        threading.Thread(target=go,daemon=True).start()
    def show_snapshot(self,s,ports):
        vals=[f"{s['files']:,}",fmt(s['bytes']),'DIRTY' if s['dirty'] else ('CLEAN' if s['git'] else '—'),s['branch'] or '—',', '.join(map(str,ports)) or 'none']
        for l,v in zip(self.card_labels,vals):l.config(text=v)
    def save_notes(self):
        p=self.current();
        if p:p.notes=self.notes.get('1.0','end').rstrip();save_state(self.state)
    def add_run(self):
        p=self.current();
        if not p:return
        name=simpledialog.askstring('Run config','Name:');
        if not name:return
        command=simpledialog.askstring('Run config','Command (for example: npm run dev):');
        if not command:return
        p.run_configs.append(RunConfig(uuid.uuid4().hex,name,command));save_state(self.state);self.refresh_runs(p)
    def refresh_runs(self,p):
        self.run_tree.delete(*self.run_tree.get_children())
        for c in p.run_configs:
            mp=self.managed.get(c.id);state='RUNNING' if mp and mp.running else ('EXIT '+str(mp.returncode) if mp and mp.returncode is not None else 'IDLE');self.run_tree.insert('','end',iid=c.id,values=(c.name,c.command,state))
    def run_selected(self):
        p=self.current();sel=self.run_tree.selection();
        if not p or not sel:return
        c=next(x for x in p.run_configs if x.id==sel[0]);mp=ManagedProcess(c,p);self.managed[c.id]=mp
        try:pid=mp.start(lambda line:self.after(0,lambda:self.append_log(p.name,c.name,line)),lambda rc:self.after(0,lambda:self.process_exit(p,c,rc)))
        except Exception as e:messagebox.showerror('Switchyard',str(e));return
        self.append_log(p.name,c.name,f'▶ started pid {pid}');self.refresh_runs(p);self.refresh_live()
    def stop_selected(self):
        sel=self.run_tree.selection();
        if sel and sel[0] in self.managed:self.managed[sel[0]].stop();self.refresh_live()
    def append_log(self,p,c,line):self.log.insert('end',f'[{p}/{c}] {line}\n');self.log.see('end')
    def process_exit(self,p,c,rc):self.append_log(p.name,c.name,f'■ exited {rc}');self.refresh_runs(p);self.refresh_live()
    def refresh_live(self):
        self.live_tree.delete(*self.live_tree.get_children());now=time.time()
        for cid,mp in self.managed.items():
            pid=mp.process.pid if mp.process else '';up=f'{int(now-mp.started_at)}s' if mp.started_at else '';state='RUNNING' if mp.running else f'EXIT {mp.returncode}';self.live_tree.insert('','end',iid=cid,values=(mp.project.name,mp.config.name,pid,up,state))
    def tick(self):
        self.refresh_live()
        p=self.current()
        if p:self.refresh_runs(p)
        self.after(1000,self.tick)
    def destroy(self):
        for mp in self.managed.values():
            if mp.running:mp.stop()
        super().destroy()
if __name__=='__main__':SwitchyardApp().mainloop()