from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from switchyard_core import (
    ManagedProcess, Project, ReadinessCheck, RunConfig, RunRecord, Service,
    SessionController, WorkspaceSession, detect_project, load_state, new_project,
    new_service, project_health, project_snapshot, readiness_description,
    save_state, scan_local_ports, service_project, suggested_run_configs,
    topological_service_order, validate_service_graph,
)

BG = '#090b0f'; PANEL = '#11161d'; PANEL2 = '#171e27'; TEXT = '#f2efe7'; MUTED = '#8f99a6'
GOLD = '#d9a84e'; CYAN = '#5dbde7'; GREEN = '#7edb9b'; RED = '#ff776f'; ORANGE = '#f0a35b'


def fmt_bytes(n):
    n = float(n)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024 or unit == 'TB': return f'{n:.1f} {unit}'
        n /= 1024


def fmt_duration(seconds):
    if seconds is None: return '—'
    seconds = int(seconds)
    if seconds < 60: return f'{seconds}s'
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60: return f'{minutes}m {seconds}s'
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes}m'


def open_folder(path):
    try:
        if os.name == 'nt': os.startfile(path)
        elif sys.platform == 'darwin': subprocess.Popen(['open', path])
        else: subprocess.Popen(['xdg-open', path])
    except Exception as exc:
        messagebox.showerror('Switchyard', f'Could not open folder:\n{exc}')


class ServiceDialog(tk.Toplevel):
    def __init__(self, parent, state, service=None, default_project=None):
        super().__init__(parent); self.title('Service'); self.configure(bg=BG); self.resizable(False, False); self.transient(parent); self.grab_set(); self.result = None
        self.state = state; self.service = service; self.projects = state.projects
        pad = {'padx': 12, 'pady': 5}
        tk.Label(self, text='SERVICE DEFINITION', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).grid(row=0, column=0, columnspan=2, sticky='w', **pad)
        fields = [('Name', 'name'), ('Command', 'command'), ('Working directory', 'cwd'), ('Readiness kind', 'kind'), ('Readiness target', 'target'), ('Timeout seconds', 'timeout')]
        self.vars = {}
        for row, (label, key) in enumerate(fields, 1):
            tk.Label(self, text=label, bg=BG, fg=MUTED).grid(row=row, column=0, sticky='w', **pad)
            var = tk.StringVar(); self.vars[key] = var
            if key == 'kind':
                widget = ttk.Combobox(self, textvariable=var, values=['process', 'port', 'delay'], state='readonly', width=46)
            else:
                widget = ttk.Entry(self, textvariable=var, width=49)
            widget.grid(row=row, column=1, **pad)
        row = 7
        tk.Label(self, text='Project', bg=BG, fg=MUTED).grid(row=row, column=0, sticky='w', **pad)
        self.project_var = tk.StringVar(); self.project_map = {p.name: p.id for p in self.projects}
        ttk.Combobox(self, textvariable=self.project_var, values=list(self.project_map), state='readonly', width=46).grid(row=row, column=1, **pad)
        row += 1
        tk.Label(self, text='Dependencies', bg=BG, fg=MUTED).grid(row=row, column=0, sticky='nw', **pad)
        self.dep_list = tk.Listbox(self, selectmode='multiple', exportselection=False, bg=PANEL, fg=TEXT, selectbackground='#26384a', width=48, height=7, highlightthickness=0)
        self.dep_list.grid(row=row, column=1, **pad)
        self.dep_services = [s for s in state.services if not service or s.id != service.id]
        for dep in self.dep_services: self.dep_list.insert('end', dep.name)
        row += 1
        tk.Label(self, text='Failure policy', bg=BG, fg=MUTED).grid(row=row, column=0, sticky='w', **pad)
        self.failure_var = tk.StringVar(value='stop_dependents')
        ttk.Combobox(self, textvariable=self.failure_var, values=['stop_dependents', 'continue'], state='readonly', width=46).grid(row=row, column=1, **pad)
        row += 1
        buttons = tk.Frame(self, bg=BG); buttons.grid(row=row, column=0, columnspan=2, sticky='e', padx=12, pady=12)
        ttk.Button(buttons, text='Cancel', command=self.destroy).pack(side='right', padx=(8, 0)); ttk.Button(buttons, text='Save service', style='Accent.TButton', command=self.save).pack(side='right')
        if service:
            self.vars['name'].set(service.name); self.vars['command'].set(service.command); self.vars['cwd'].set(service.cwd or '')
            self.vars['kind'].set(service.readiness.kind); self.vars['target'].set(service.readiness.target); self.vars['timeout'].set(str(service.readiness.timeout)); self.failure_var.set(service.failure_policy)
            project = next((p for p in self.projects if p.id == service.project_id), None); self.project_var.set(project.name if project else '')
            for i, dep in enumerate(self.dep_services):
                if dep.id in service.depends_on: self.dep_list.selection_set(i)
        else:
            self.vars['kind'].set('process'); self.vars['timeout'].set('30')
            project = default_project or (self.projects[0] if self.projects else None); self.project_var.set(project.name if project else '')
        self.bind('<Escape>', lambda _e: self.destroy()); self.wait_visibility(); self.focus_force()

    def save(self):
        project_id = self.project_map.get(self.project_var.get())
        name = self.vars['name'].get().strip(); command = self.vars['command'].get().strip()
        if not project_id or not name or not command:
            messagebox.showwarning('Switchyard', 'Project, name and command are required.', parent=self); return
        try: timeout = max(.1, float(self.vars['timeout'].get() or 30))
        except ValueError: messagebox.showwarning('Switchyard', 'Timeout must be a number.', parent=self); return
        deps = [self.dep_services[i].id for i in self.dep_list.curselection()]
        readiness = ReadinessCheck(self.vars['kind'].get() or 'process', self.vars['target'].get().strip(), timeout)
        sid = self.service.id if self.service else uuid.uuid4().hex
        self.result = Service(sid, project_id, name, command, self.vars['cwd'].get().strip() or None, {}, deps, readiness, self.failure_var.get())
        self.destroy()


class SessionDialog(tk.Toplevel):
    def __init__(self, parent, state, session=None):
        super().__init__(parent); self.title('Workspace session'); self.configure(bg=BG); self.resizable(False, False); self.transient(parent); self.grab_set(); self.result = None; self.session = session
        tk.Label(self, text='WORKSPACE SESSION', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(anchor='w', padx=14, pady=(14, 6))
        row = tk.Frame(self, bg=BG); row.pack(fill='x', padx=14, pady=6); tk.Label(row, text='Name', bg=BG, fg=MUTED, width=14, anchor='w').pack(side='left'); self.name_var = tk.StringVar(value=session.name if session else ''); ttk.Entry(row, textvariable=self.name_var, width=44).pack(side='left')
        tk.Label(self, text='Services in this session', bg=BG, fg=MUTED).pack(anchor='w', padx=14, pady=(8, 4))
        self.services = list(state.services); self.list = tk.Listbox(self, selectmode='multiple', exportselection=False, bg=PANEL, fg=TEXT, selectbackground='#26384a', width=62, height=12, highlightthickness=0); self.list.pack(padx=14, pady=(0, 8))
        project_names = {p.id: p.name for p in state.projects}
        for i, service in enumerate(self.services):
            self.list.insert('end', f'{service.name}  ·  {project_names.get(service.project_id, "missing project")}')
            if session and service.id in session.service_ids: self.list.selection_set(i)
        buttons = tk.Frame(self, bg=BG); buttons.pack(fill='x', padx=14, pady=(4, 14)); ttk.Button(buttons, text='Cancel', command=self.destroy).pack(side='right', padx=(8, 0)); ttk.Button(buttons, text='Save session', style='Accent.TButton', command=self.save).pack(side='right')
        self.bind('<Escape>', lambda _e: self.destroy()); self.wait_visibility(); self.focus_force()

    def save(self):
        name = self.name_var.get().strip(); ids = [self.services[i].id for i in self.list.curselection()]
        if not name or not ids: messagebox.showwarning('Switchyard', 'Give the session a name and select at least one service.', parent=self); return
        session_id = getattr(self.session, 'id', None)
        self.result = WorkspaceSession(session_id or uuid.uuid4().hex, name, ids); self.destroy()


class SwitchyardApp(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('Switchyard — Local Developer Command Center'); self.geometry('1520x930'); self.minsize(1160, 740); self.configure(bg=BG)
        self.state = load_state(); self.managed: dict[str, ManagedProcess] = {}; self.run_records: dict[str, RunRecord] = {}; self.detected = {}; self.session_controllers: dict[str, SessionController] = {}
        self._style(); self._build(); self.refresh_projects(self.state.selected_project); self.refresh_services(); self.refresh_sessions(); self.refresh_session_timeline(); self.after(1000, self.tick)

    def _style(self):
        s = ttk.Style(self); s.theme_use('clam'); s.configure('.', background=BG, foreground=TEXT, fieldbackground=PANEL)
        s.configure('TButton', background='#1d2630', foreground=TEXT, padding=8, borderwidth=0); s.map('TButton', background=[('active', '#293745')])
        s.configure('Accent.TButton', background='#6f5624', foreground='#fff7dc', padding=9); s.map('Accent.TButton', background=[('active', '#8b6b2c')])
        s.configure('Danger.TButton', background='#55262a', foreground='#ffe7e5', padding=8); s.map('Danger.TButton', background=[('active', '#74333a')])
        s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=29, borderwidth=0); s.map('Treeview', background=[('selected', '#26384a')])
        s.configure('Treeview.Heading', background=PANEL2, foreground=TEXT, relief='flat'); s.configure('TNotebook', background=BG, borderwidth=0); s.configure('TNotebook.Tab', background=PANEL, foreground=MUTED, padding=(12, 8), font=('Segoe UI', 9)); s.map('TNotebook.Tab', background=[('selected', PANEL2)], foreground=[('selected', TEXT)])

    def _build(self):
        top = tk.Frame(self, bg=BG); top.pack(fill='x', padx=18, pady=(14, 8)); tk.Label(top, text='SWITCHYARD', bg=BG, fg=TEXT, font=('Segoe UI Semibold', 26)).pack(side='left'); tk.Label(top, text='  workspace intelligence + service orchestration', bg=BG, fg=MUTED).pack(side='left', pady=(10, 0)); ttk.Button(top, text='+ Add project', style='Accent.TButton', command=self.add_project).pack(side='right')
        main = tk.PanedWindow(self, orient='horizontal', bg='#202733', sashwidth=1); main.pack(fill='both', expand=True, padx=18, pady=(0, 18)); self.sidebar = tk.Frame(main, bg=PANEL, width=285); self.content = tk.Frame(main, bg=BG); main.add(self.sidebar, minsize=250); main.add(self.content, minsize=790)
        side_head = tk.Frame(self.sidebar, bg=PANEL); side_head.pack(fill='x', padx=14, pady=(14, 8)); tk.Label(side_head, text='PROJECTS', bg=PANEL, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(side='left'); self.project_count = tk.Label(side_head, text='0', bg=PANEL, fg=MUTED, font=('Consolas', 9)); self.project_count.pack(side='right')
        self.project_list = tk.Listbox(self.sidebar, bg=PANEL, fg=TEXT, selectbackground='#273646', highlightthickness=0, borderwidth=0, font=('Segoe UI', 11), activestyle='none'); self.project_list.pack(fill='both', expand=True, padx=8, pady=(0, 8)); self.project_list.bind('<<ListboxSelect>>', self.on_project)
        side_actions = tk.Frame(self.sidebar, bg=PANEL); side_actions.pack(fill='x', padx=10, pady=10); ttk.Button(side_actions, text='Pin / unpin', command=self.toggle_pin).pack(fill='x', pady=(0, 6)); ttk.Button(side_actions, text='Tags', command=self.edit_tags).pack(fill='x', pady=(0, 6)); ttk.Button(side_actions, text='Remove', command=self.remove_project).pack(fill='x')
        self.header = tk.Frame(self.content, bg=BG); self.header.pack(fill='x', padx=18, pady=(8, 12)); title_row = tk.Frame(self.header, bg=BG); title_row.pack(fill='x'); self.project_title = tk.Label(title_row, text='Select a project', bg=BG, fg=TEXT, font=('Segoe UI Semibold', 24)); self.project_title.pack(side='left'); ttk.Button(title_row, text='Open folder', command=self.open_current_folder).pack(side='right'); self.project_meta = tk.Label(self.header, text='', bg=BG, fg=MUTED, font=('Consolas', 10), justify='left'); self.project_meta.pack(anchor='w', pady=(4, 0)); self.project_tags = tk.Label(self.header, text='', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)); self.project_tags.pack(anchor='w', pady=(5, 0))
        self.nb = ttk.Notebook(self.content); self.nb.pack(fill='both', expand=True, padx=18, pady=(0, 12))
        self.overview = tk.Frame(self.nb, bg=BG); self.intelligence = tk.Frame(self.nb, bg=BG); self.runs = tk.Frame(self.nb, bg=BG); self.services_tab = tk.Frame(self.nb, bg=BG); self.sessions_tab = tk.Frame(self.nb, bg=BG); self.history = tk.Frame(self.nb, bg=BG); self.live = tk.Frame(self.nb, bg=BG)
        for frame, title in [(self.overview,'Overview'),(self.intelligence,'Intelligence'),(self.runs,'Run configurations'),(self.services_tab,'Services'),(self.sessions_tab,'Sessions'),(self.history,'History'),(self.live,'Live processes')]: self.nb.add(frame, text=title)
        self._overview(); self._intelligence(); self._runs(); self._services(); self._sessions(); self._history(); self._live()

    def _overview(self):
        self.cards = tk.Frame(self.overview, bg=BG); self.cards.pack(fill='x', pady=12); self.card_labels = []
        for label in ['FILES','SIZE','GIT','BRANCH','STACK','PORTS']:
            frame = tk.Frame(self.cards, bg=PANEL, highlightbackground='#222b35', highlightthickness=1); frame.pack(side='left', fill='both', expand=True, padx=4); tk.Label(frame, text=label, bg=PANEL, fg=MUTED, font=('Segoe UI Semibold', 8)).pack(anchor='w', padx=12, pady=(10,2)); value = tk.Label(frame, text='—', bg=PANEL, fg=TEXT, font=('Segoe UI Semibold',15), wraplength=160, justify='left'); value.pack(anchor='w', padx=12, pady=(0,12)); self.card_labels.append(value)
        self.git_detail = tk.Label(self.overview, text='', bg=BG, fg=MUTED, font=('Consolas',10), justify='left'); self.git_detail.pack(anchor='w', padx=4, pady=(10,2)); tk.Label(self.overview, text='NOTES', bg=BG, fg=GOLD, font=('Segoe UI Semibold',9)).pack(anchor='w', pady=(18,4)); self.notes = tk.Text(self.overview, bg=PANEL, fg=TEXT, insertbackground=TEXT, height=10, relief='flat', wrap='word'); self.notes.pack(fill='both', expand=True); self.notes.bind('<FocusOut>', lambda _e:self.save_notes())

    def _intelligence(self):
        top = tk.Frame(self.intelligence, bg=BG); top.pack(fill='x', pady=(10,6)); ttk.Button(top,text='Refresh intelligence',command=self.refresh_intelligence).pack(side='left'); ttk.Button(top,text='Import detected tasks',style='Accent.TButton',command=self.import_detected_tasks).pack(side='left',padx=8); self.stack_summary = tk.Label(self.intelligence,text='No project selected',bg=PANEL,fg=TEXT,anchor='w',justify='left',padx=14,pady=12,font=('Segoe UI Semibold',11)); self.stack_summary.pack(fill='x',pady=(4,12))
        split = tk.PanedWindow(self.intelligence,orient='horizontal',bg='#202733',sashwidth=1); split.pack(fill='both',expand=True); left=tk.Frame(split,bg=BG); right=tk.Frame(split,bg=BG); split.add(left,minsize=420);split.add(right,minsize=420); tk.Label(left,text='DETECTED TASKS',bg=BG,fg=CYAN,font=('Segoe UI Semibold',9)).pack(anchor='w',pady=(0,4)); self.task_tree=ttk.Treeview(left,columns=('name','command','source'),show='headings')
        for col,title,width in [('name','NAME',140),('command','COMMAND',270),('source','SOURCE',130)]: self.task_tree.heading(col,text=title); self.task_tree.column(col,width=width)
        self.task_tree.pack(fill='both',expand=True,padx=(0,6)); tk.Label(right,text='HEALTH',bg=BG,fg=GREEN,font=('Segoe UI Semibold',9)).pack(anchor='w',pady=(0,4)); self.health_tree=ttk.Treeview(right,columns=('state','check','detail'),show='headings')
        for col,title,width in [('state','STATE',80),('check','CHECK',190),('detail','DETAIL',220)]: self.health_tree.heading(col,text=title); self.health_tree.column(col,width=width)
        self.health_tree.pack(fill='both',expand=True,padx=(6,0))

    def _runs(self):
        bar=tk.Frame(self.runs,bg=BG);bar.pack(fill='x',pady=10); ttk.Button(bar,text='+ Add run config',command=self.add_run).pack(side='left'); ttk.Button(bar,text='Edit',command=self.edit_run).pack(side='left',padx=(8,0)); ttk.Button(bar,text='Delete',command=self.delete_run).pack(side='left',padx=8); ttk.Button(bar,text='Promote to service',command=self.promote_run_to_service).pack(side='left',padx=(12,0)); ttk.Button(bar,text='Run',style='Accent.TButton',command=self.run_selected).pack(side='right',padx=(8,0)); ttk.Button(bar,text='Restart',command=self.restart_selected).pack(side='right'); ttk.Button(bar,text='Stop',command=self.stop_selected).pack(side='right',padx=8)
        self.run_tree=ttk.Treeview(self.runs,columns=('name','command','cwd','state'),show='headings')
        for col,title,width in [('name','NAME',180),('command','COMMAND',500),('cwd','CWD',220),('state','STATE',110)]: self.run_tree.heading(col,text=title); self.run_tree.column(col,width=width)
        self.run_tree.pack(fill='both',expand=True)

    def _services(self):
        bar=tk.Frame(self.services_tab,bg=BG);bar.pack(fill='x',pady=10); ttk.Button(bar,text='+ New service',style='Accent.TButton',command=self.add_service).pack(side='left'); ttk.Button(bar,text='Edit',command=self.edit_service).pack(side='left',padx=8); ttk.Button(bar,text='Delete',command=self.delete_service).pack(side='left'); ttk.Button(bar,text='Validate graph',command=self.validate_graph).pack(side='left',padx=12); ttk.Button(bar,text='Run service',command=self.run_service).pack(side='right',padx=(8,0)); ttk.Button(bar,text='Stop service',command=self.stop_service).pack(side='right')
        self.service_tree=ttk.Treeview(self.services_tab,columns=('name','project','command','deps','ready','state'),show='headings')
        for col,title,width in [('name','SERVICE',160),('project','PROJECT',150),('command','COMMAND',360),('deps','DEPENDS ON',190),('ready','READINESS',180),('state','STATE',100)]: self.service_tree.heading(col,text=title); self.service_tree.column(col,width=width)
        self.service_tree.pack(fill='both',expand=True); self.service_note=tk.Label(self.services_tab,text='Services can span projects. Sessions start them in dependency order and wait for readiness before continuing.',bg=BG,fg=MUTED,anchor='w',justify='left');self.service_note.pack(fill='x',pady=(8,0))

    def _sessions(self):
        upper=tk.Frame(self.sessions_tab,bg=BG);upper.pack(fill='x',pady=10); ttk.Button(upper,text='+ New session',style='Accent.TButton',command=self.add_session).pack(side='left'); ttk.Button(upper,text='Edit',command=self.edit_session).pack(side='left',padx=8); ttk.Button(upper,text='Delete',command=self.delete_session).pack(side='left'); ttk.Button(upper,text='Start session',command=self.start_session).pack(side='right',padx=(8,0)); ttk.Button(upper,text='Stop session',style='Danger.TButton',command=self.stop_session).pack(side='right')
        split=tk.PanedWindow(self.sessions_tab,orient='vertical',bg='#202733',sashwidth=1);split.pack(fill='both',expand=True); top=tk.Frame(split,bg=BG);bottom=tk.Frame(split,bg=BG);split.add(top,minsize=200);split.add(bottom,minsize=230)
        self.session_tree=ttk.Treeview(top,columns=('name','services','state'),show='headings');
        for col,title,width in [('name','SESSION',220),('services','SERVICES',650),('state','STATE',120)]: self.session_tree.heading(col,text=title); self.session_tree.column(col,width=width)
        self.session_tree.pack(fill='both',expand=True); self.session_tree.bind('<<TreeviewSelect>>',lambda _e:self.refresh_session_detail())
        head=tk.Frame(bottom,bg=BG);head.pack(fill='x',pady=(8,4));tk.Label(head,text='SESSION TOPOLOGY + TIMELINE',bg=BG,fg=GOLD,font=('Segoe UI Semibold',9)).pack(side='left');ttk.Button(head,text='Clear timeline',command=self.clear_session_history).pack(side='right')
        inner=tk.PanedWindow(bottom,orient='horizontal',bg='#202733',sashwidth=1);inner.pack(fill='both',expand=True);left=tk.Frame(inner,bg=BG);right=tk.Frame(inner,bg=BG);inner.add(left,minsize=440);inner.add(right,minsize=440);self.session_detail=tk.Text(left,bg='#07090c',fg='#c9d5df',insertbackground=TEXT,relief='flat',font=('Consolas',10),wrap='none');self.session_detail.pack(fill='both',expand=True,padx=(0,5));self.timeline_tree=ttk.Treeview(right,columns=('time','kind','message'),show='headings');
        for col,title,width in [('time','TIME',85),('kind','EVENT',110),('message','MESSAGE',420)]: self.timeline_tree.heading(col,text=title);self.timeline_tree.column(col,width=width)
        self.timeline_tree.pack(fill='both',expand=True,padx=(5,0))

    def _history(self):
        bar=tk.Frame(self.history,bg=BG);bar.pack(fill='x',pady=10);tk.Label(bar,text='RECENT RUNS',bg=BG,fg=GOLD,font=('Segoe UI Semibold',9)).pack(side='left');ttk.Button(bar,text='Clear history',command=self.clear_history).pack(side='right');self.history_tree=ttk.Treeview(self.history,columns=('time','project','config','result','duration','pid'),show='headings')
        for col,title,width in [('time','STARTED',170),('project','PROJECT',170),('config','CONFIG',180),('result','RESULT',110),('duration','DURATION',100),('pid','PID',90)]:self.history_tree.heading(col,text=title);self.history_tree.column(col,width=width)
        self.history_tree.pack(fill='both',expand=True)

    def _live(self):
        self.live_tree=ttk.Treeview(self.live,columns=('project','config','pid','uptime','state'),show='headings');
        for col,title,width in [('project','PROJECT',180),('config','CONFIG',180),('pid','PID',90),('uptime','UPTIME',120),('state','STATE',120)]:self.live_tree.heading(col,text=title);self.live_tree.column(col,width=width)
        self.live_tree.pack(fill='x',pady=(10,8));tk.Label(self.live,text='COMBINED OUTPUT',bg=BG,fg=GOLD,font=('Segoe UI Semibold',9)).pack(anchor='w');self.log=tk.Text(self.live,bg='#07090c',fg='#b7c5d3',insertbackground=TEXT,relief='flat',font=('Consolas',10));self.log.pack(fill='both',expand=True,pady=(4,0))

    def current(self):
        selection=self.project_list.curselection()
        if not selection:return None
        ids=getattr(self,'_project_list_ids',[])
        if selection[0]>=len(ids):return None
        project_id=ids[selection[0]];return next((p for p in self.state.projects if p.id==project_id),None)
    def _ordered_projects(self):return sorted(self.state.projects,key=lambda p:(not p.pinned,-(p.last_opened or 0),p.name.lower()))
    def refresh_projects(self,select=None):
        self.project_list.delete(0,'end');self._project_list_ids=[];ordered=self._ordered_projects();target=select or self.state.selected_project;target_index=None
        for i,p in enumerate(ordered):
            marker='★ ' if p.pinned else '';tags=f"  [{', '.join(p.tags)}]" if p.tags else '';self.project_list.insert('end',f'{marker}{p.name}{tags}');self._project_list_ids.append(p.id);target_index=i if p.id==target else target_index
        self.project_count.config(text=str(len(ordered)))
        if ordered:
            idx=target_index if target_index is not None else 0;self.project_list.selection_set(idx);self.project_list.see(idx);self.project_list.event_generate('<<ListboxSelect>>')
    def add_project(self):
        path=filedialog.askdirectory();
        if not path:return
        resolved=str(Path(path).resolve());existing=next((p for p in self.state.projects if str(Path(p.path).resolve())==resolved),None)
        if existing:self.refresh_projects(existing.id);return
        proj=new_project(path);self.state.projects.append(proj);self.state.selected_project=proj.id;save_state(self.state);self.refresh_projects(proj.id);self.refresh_services()
    def remove_project(self):
        p=self.current();
        if not p:return
        if any(mp.running and mp.project.id==p.id for mp in self.managed.values()):messagebox.showwarning('Switchyard','Stop this project\'s running processes before removing it.');return
        if any(s.project_id==p.id for s in self.state.services):messagebox.showwarning('Switchyard','Remove or reassign this project\'s services first.');return
        if messagebox.askyesno('Switchyard',f'Remove {p.name} from Switchyard? Files will not be touched.'):
            self.state.projects=[x for x in self.state.projects if x.id!=p.id];self.state.selected_project=None if self.state.selected_project==p.id else self.state.selected_project;save_state(self.state);self.refresh_projects()
    def toggle_pin(self):
        p=self.current();
        if p:p.pinned=not p.pinned;save_state(self.state);self.refresh_projects(p.id)
    def edit_tags(self):
        p=self.current();
        if not p:return
        value=simpledialog.askstring('Project tags','Comma-separated tags:',initialvalue=', '.join(p.tags));
        if value is None:return
        p.tags=sorted({x.strip() for x in value.split(',') if x.strip()});save_state(self.state);self.refresh_projects(p.id)
    def open_current_folder(self):
        p=self.current();
        if p:open_folder(p.path)
    def on_project(self,_event=None):
        p=self.current();
        if not p:return
        p.last_opened=time.time();self.state.selected_project=p.id;save_state(self.state);self.project_title.config(text=('★ ' if p.pinned else '')+p.name);self.project_meta.config(text=p.path);self.project_tags.config(text=' · '.join(p.tags).upper() if p.tags else '');self.notes.delete('1.0','end');self.notes.insert('1.0',p.notes);self.refresh_snapshot(p);self.refresh_runs(p);self.refresh_intelligence();self.refresh_history()
    def refresh_snapshot(self,p):
        def go():
            snap=project_snapshot(p);detected=detect_project(p.path);likely_ports=detected['ports'] or [3000,4173,5173,8000,8080,1420,5000];ports=scan_local_ports(likely_ports);self.after(0,lambda:self.show_snapshot(p.id,snap,detected,ports))
        threading.Thread(target=go,daemon=True).start()
    def show_snapshot(self,project_id,snap,detected,ports):
        p=self.current();
        if not p or p.id!=project_id:return
        git_state='—'
        if snap['git']:git_state=f"{snap['changed']} change"+('s' if snap['changed']!=1 else '') if snap['dirty'] else 'CLEAN'
        stack=' · '.join(detected['stacks'][:3]) or 'Unknown';vals=[f"{snap['files']:,}",fmt_bytes(snap['bytes']),git_state,snap['branch'] or '—',stack,', '.join(map(str,ports)) or 'none']
        for label,value in zip(self.card_labels,vals):label.config(text=value)
        detail=[]
        if snap['upstream']:detail.append(f"upstream {snap['upstream']} · ↑{snap['ahead']} ↓{snap['behind']}")
        if snap['last_commit']:detail.append(f"last {snap['last_commit']}")
        if snap['remote']:detail.append(f"origin {snap['remote']}")
        self.git_detail.config(text='\n'.join(detail))
    def save_notes(self):
        p=self.current();
        if p:p.notes=self.notes.get('1.0','end').rstrip();save_state(self.state)
    def refresh_intelligence(self):
        p=self.current();
        if not p:return
        project_id=p.id;self.stack_summary.config(text='Inspecting project metadata…');self.task_tree.delete(*self.task_tree.get_children());self.health_tree.delete(*self.health_tree.get_children())
        def go():
            detected=detect_project(p.path);health=project_health(p);self.after(0,lambda:self.show_intelligence(project_id,detected,health))
        threading.Thread(target=go,daemon=True).start()
    def show_intelligence(self,project_id,detected,health):
        p=self.current();
        if not p or p.id!=project_id:return
        self.detected[project_id]=detected;stack_text=' · '.join(detected['stacks']) or 'No known stack detected';evidence=', '.join(detected['evidence']) or 'no recognized manifests';self.stack_summary.config(text=f'{stack_text}\nEvidence: {evidence}');self.task_tree.delete(*self.task_tree.get_children())
        for i,task in enumerate(detected['tasks']):self.task_tree.insert('','end',iid=f'task-{i}',values=(task['name'],task['command'],task['source']))
        self.health_tree.delete(*self.health_tree.get_children())
        for i,check in enumerate(health):
            state='PASS' if check['ok'] else ('INFO' if check['kind']=='port' else 'CHECK');self.health_tree.insert('','end',iid=f'health-{i}',values=(state,check['name'],check['detail']))
    def import_detected_tasks(self):
        p=self.current();
        if not p:return
        suggestions=suggested_run_configs(p)
        if not suggestions:messagebox.showinfo('Switchyard','No new detected tasks to import.');return
        summary='\n'.join(f'• {c.name}: {c.command}' for c in suggestions)
        if not messagebox.askyesno('Import detected tasks',f'Add these run configurations?\n\n{summary}'):return
        p.run_configs.extend(suggestions);save_state(self.state);self.refresh_runs(p);self.refresh_intelligence()
    def add_run(self):
        p=self.current();
        if not p:return
        name=simpledialog.askstring('Run configuration','Name:');
        if not name:return
        command=simpledialog.askstring('Run configuration','Command:');
        if not command:return
        cwd=simpledialog.askstring('Run configuration','Working directory (blank = project root):',initialvalue='');p.run_configs.append(RunConfig(uuid.uuid4().hex,name,command,cwd or None));save_state(self.state);self.refresh_runs(p);self.refresh_intelligence()
    def _selected_config(self):
        p=self.current();sel=self.run_tree.selection();return (p,next((x for x in p.run_configs if x.id==sel[0]),None)) if p and sel else (p,None)
    def edit_run(self):
        p,config=self._selected_config();
        if not p or not config:return
        if config.id in self.managed and self.managed[config.id].running:messagebox.showwarning('Switchyard','Stop this configuration before editing it.');return
        name=simpledialog.askstring('Run configuration','Name:',initialvalue=config.name);command=simpledialog.askstring('Run configuration','Command:',initialvalue=config.command) if name else None
        if not name or not command:return
        cwd=simpledialog.askstring('Run configuration','Working directory (blank = project root):',initialvalue=config.cwd or '');config.name,config.command,config.cwd=name,command,cwd or None;save_state(self.state);self.refresh_runs(p);self.refresh_intelligence()
    def delete_run(self):
        p,config=self._selected_config();
        if not p or not config:return
        if config.id in self.managed and self.managed[config.id].running:messagebox.showwarning('Switchyard','Stop this configuration before deleting it.');return
        if messagebox.askyesno('Switchyard',f'Delete run configuration “{config.name}”?'):p.run_configs=[c for c in p.run_configs if c.id!=config.id];self.managed.pop(config.id,None);save_state(self.state);self.refresh_runs(p);self.refresh_intelligence()
    def refresh_runs(self,p):
        selected=self.run_tree.selection();self.run_tree.delete(*self.run_tree.get_children())
        for config in p.run_configs:
            mp=self.managed.get(config.id);state='RUNNING' if mp and mp.running else (f'EXIT {mp.returncode}' if mp and mp.returncode is not None else 'IDLE');self.run_tree.insert('','end',iid=config.id,values=(config.name,config.command,config.cwd or '.',state))
        if selected and self.run_tree.exists(selected[0]):self.run_tree.selection_set(selected[0])
    def promote_run_to_service(self):
        p,config=self._selected_config();
        if not p or not config:return
        if any(s.command==config.command and s.project_id==p.id for s in self.state.services):messagebox.showinfo('Switchyard','This run configuration is already represented as a service.');return
        self.state.services.append(new_service(p,config.name,config.command,cwd=config.cwd));save_state(self.state);self.refresh_services();self.nb.select(self.services_tab)
    def run_selected(self):
        p,config=self._selected_config();
        if not p or not config:return
        existing=self.managed.get(config.id)
        if existing and existing.running:messagebox.showinfo('Switchyard',f'{config.name} is already running.');return
        mp=ManagedProcess(config,p);self.managed[config.id]=mp;record=RunRecord(uuid.uuid4().hex,p.id,p.name,config.id,config.name,config.command,time.time());self.run_records[config.id]=record;self.state.run_history.append(record);save_state(self.state)
        try:pid=mp.start(lambda line:self.after(0,lambda text=line:self.append_log(p.name,config.name,text)),lambda rc:self.after(0,lambda:self.process_exit(p,config,rc)))
        except Exception as exc:record.ended_at=time.time();record.returncode=-1;save_state(self.state);messagebox.showerror('Switchyard',str(exc));self.refresh_history();return
        record.pid=pid;save_state(self.state);self.append_log(p.name,config.name,f'▶ started pid {pid}');self.refresh_runs(p);self.refresh_live();self.refresh_history()
    def stop_selected(self):
        _p,config=self._selected_config();
        if config and config.id in self.managed:self.managed[config.id].stop();self.refresh_live()
    def restart_selected(self):
        p,config=self._selected_config();
        if not p or not config:return
        existing=self.managed.get(config.id)
        if existing and existing.running:existing.stop();self.after(250,self.run_selected)
        else:self.run_selected()
    def process_exit(self,p,config,rc):
        self.append_log(p.name,config.name,f'■ exited {rc}');record=self.run_records.pop(config.id,None)
        if record:record.ended_at=time.time();record.returncode=rc;save_state(self.state)
        self.refresh_runs(p);self.refresh_live();self.refresh_history()
        if config.auto_restart and rc!=0:self.after(1000,lambda:self._run_config_direct(p,config))
    def _run_config_direct(self,p,config):
        self.refresh_projects(p.id)
        if self.run_tree.exists(config.id):self.run_tree.selection_set(config.id);self.nb.select(self.runs);self.run_selected()

    def _selected_service(self):
        sel=self.service_tree.selection();return next((s for s in self.state.services if sel and s.id==sel[0]),None)
    def add_service(self):
        if not self.state.projects:messagebox.showinfo('Switchyard','Add a project before creating a service.');return
        dialog=ServiceDialog(self,self.state,default_project=self.current());self.wait_window(dialog)
        if dialog.result:self.state.services.append(dialog.result);self._save_and_refresh_services()
    def edit_service(self):
        service=self._selected_service();
        if not service:return
        if any(c.processes.get(service.id) and c.processes[service.id].running for c in self.session_controllers.values()):messagebox.showwarning('Switchyard','Stop this service before editing it.');return
        dialog=ServiceDialog(self,self.state,service=service);self.wait_window(dialog)
        if dialog.result:
            idx=self.state.services.index(service);self.state.services[idx]=dialog.result;self._save_and_refresh_services(dialog.result.id)
    def delete_service(self):
        service=self._selected_service();
        if not service:return
        refs=[s.name for s in self.state.services if service.id in s.depends_on];sessions=[s.name for s in self.state.sessions if service.id in s.service_ids]
        if refs or sessions:messagebox.showwarning('Switchyard','Remove this service from dependents/sessions first.\n\n'+('\n'.join(['Dependents: '+', '.join(refs)] if refs else [])+('\nSessions: '+', '.join(sessions) if sessions else '')));return
        if messagebox.askyesno('Switchyard',f'Delete service “{service.name}”?'):self.state.services=[s for s in self.state.services if s.id!=service.id];self._save_and_refresh_services()
    def _save_and_refresh_services(self,select=None):save_state(self.state);self.refresh_services(select);self.refresh_sessions();self.refresh_session_detail()
    def refresh_services(self,select=None):
        if not hasattr(self,'service_tree'):return
        selected=select or (self.service_tree.selection()[0] if self.service_tree.selection() else None);self.service_tree.delete(*self.service_tree.get_children());projects={p.id:p.name for p in self.state.projects};names={s.id:s.name for s in self.state.services}
        for service in self.state.services:
            status='IDLE'
            for controller in self.session_controllers.values():
                candidate=controller.service_status(service.id)
                if candidate!='IDLE':status=candidate;break
            deps=', '.join(names.get(d,'missing') for d in service.depends_on) or '—';self.service_tree.insert('','end',iid=service.id,values=(service.name,projects.get(service.project_id,'missing'),service.command,deps,readiness_description(service.readiness),status))
        if selected and self.service_tree.exists(selected):self.service_tree.selection_set(selected)
    def validate_graph(self):
        errors=validate_service_graph(self.state.services)
        messagebox.showerror('Service graph','\n'.join(errors)) if errors else messagebox.showinfo('Service graph','Service dependency graph is valid.')
    def run_service(self):
        service=self._selected_service();
        if not service:return
        temp=WorkspaceSession('adhoc-'+uuid.uuid4().hex,'Ad-hoc service',[service.id]);controller=SessionController(self.state,temp,on_event=self.on_session_event,on_line=self.on_service_line);self.session_controllers[temp.id]=controller
        try:controller.start()
        except Exception as exc:messagebox.showerror('Switchyard',str(exc));return
        self.nb.select(self.sessions_tab);self.refresh_sessions();self.refresh_services()
    def stop_service(self):
        service=self._selected_service();
        if not service:return
        for controller in self.session_controllers.values():
            process=controller.processes.get(service.id)
            if process and process.running:process.stop();controller.ready.discard(service.id);controller._emit('service-stop',f'{service.name} stopped manually',service.id);break
        self.refresh_services()

    def _selected_session(self):
        sel=self.session_tree.selection();return next((s for s in self.state.sessions if sel and s.id==sel[0]),None)
    def add_session(self):
        if not self.state.services:messagebox.showinfo('Switchyard','Create at least one service first.');return
        dialog=SessionDialog(self,self.state);self.wait_window(dialog)
        if dialog.result:self.state.sessions.append(dialog.result);save_state(self.state);self.refresh_sessions(dialog.result.id);self.refresh_session_detail()
    def edit_session(self):
        session=self._selected_session();
        if not session:return
        controller=self.session_controllers.get(session.id)
        if controller and controller.running:messagebox.showwarning('Switchyard','Stop this session before editing it.');return
        dialog=SessionDialog(self,self.state,session);self.wait_window(dialog)
        if dialog.result:
            idx=self.state.sessions.index(session);self.state.sessions[idx]=dialog.result;save_state(self.state);self.refresh_sessions(dialog.result.id);self.refresh_session_detail()
    def delete_session(self):
        session=self._selected_session();
        if not session:return
        controller=self.session_controllers.get(session.id)
        if controller and controller.running:messagebox.showwarning('Switchyard','Stop this session before deleting it.');return
        if messagebox.askyesno('Switchyard',f'Delete session “{session.name}”?'):self.state.sessions=[s for s in self.state.sessions if s.id!=session.id];self.session_controllers.pop(session.id,None);save_state(self.state);self.refresh_sessions();self.refresh_session_detail()
    def start_session(self):
        session=self._selected_session();
        if not session:return
        try:topological_service_order(self.state.services,session.service_ids)
        except ValueError as exc:messagebox.showerror('Switchyard',f'Fix this session dependency graph before starting:\n\n{exc}');return
        controller=self.session_controllers.get(session.id)
        if controller and (controller.running or controller.status=='STARTING'):messagebox.showinfo('Switchyard','This session is already active.');return
        controller=SessionController(self.state,session,on_event=self.on_session_event,on_line=self.on_service_line);self.session_controllers[session.id]=controller
        try:controller.start()
        except Exception as exc:messagebox.showerror('Switchyard',str(exc));return
        self.refresh_sessions(session.id);self.refresh_session_detail();self.refresh_services()
    def stop_session(self):
        session=self._selected_session();
        if not session:return
        controller=self.session_controllers.get(session.id)
        if controller:threading.Thread(target=controller.stop,daemon=True).start()
        self.after(100,self.refresh_sessions);self.after(100,self.refresh_services)
    def refresh_sessions(self,select=None):
        if not hasattr(self,'session_tree'):return
        selected=select or (self.session_tree.selection()[0] if self.session_tree.selection() else None);self.session_tree.delete(*self.session_tree.get_children());names={s.id:s.name for s in self.state.services}
        for session in self.state.sessions:
            controller=self.session_controllers.get(session.id);state=controller.status if controller else 'IDLE';services=' → '.join(names.get(sid,'missing') for sid in session.service_ids);self.session_tree.insert('','end',iid=session.id,values=(session.name,services,state))
        if selected and self.session_tree.exists(selected):self.session_tree.selection_set(selected)
    def refresh_session_detail(self):
        if not hasattr(self,'session_detail'):return
        self.session_detail.delete('1.0','end');session=self._selected_session()
        if not session:self.session_detail.insert('1.0','Select a workspace session to inspect its topology.');return
        names={s.id:s.name for s in self.state.services};controller=self.session_controllers.get(session.id)
        try:order=topological_service_order(self.state.services,session.service_ids)
        except ValueError as exc:self.session_detail.insert('end',f'GRAPH ERROR\n{exc}\n');return
        self.session_detail.insert('end',f'{session.name.upper()}\n');self.session_detail.insert('end','═'*48+'\n')
        for service in order:
            project=service_project(service,self.state);deps=', '.join(names.get(d,'missing') for d in service.depends_on) or 'none';status=controller.service_status(service.id) if controller else 'IDLE';self.session_detail.insert('end',f'[{status:<8}] {service.name}\n  project   {project.name if project else "missing"}\n  depends   {deps}\n  ready     {readiness_description(service.readiness)}\n  command   {service.command}\n\n')
    def on_session_event(self,event):
        def apply():
            save_state(self.state);self.refresh_session_timeline();self.refresh_sessions(event.session_id);self.refresh_services();self.refresh_session_detail();self.append_log('SESSION',event.kind,event.message)
        self.after(0,apply)
    def on_service_line(self,service,line):
        project=service_project(service,self.state);self.after(0,lambda:self.append_log(project.name if project else 'service',service.name,line))
    def refresh_session_timeline(self):
        if not hasattr(self,'timeline_tree'):return
        self.timeline_tree.delete(*self.timeline_tree.get_children())
        for i,event in enumerate(reversed(self.state.session_history[-250:])):
            stamp=time.strftime('%H:%M:%S',time.localtime(event.timestamp));self.timeline_tree.insert('','end',iid=f'ev-{i}',values=(stamp,event.kind.upper(),event.message))
    def clear_session_history(self):
        if messagebox.askyesno('Switchyard','Clear the saved session timeline?'):self.state.session_history.clear();save_state(self.state);self.refresh_session_timeline()

    def append_log(self,project,config,line):
        self.log.insert('end',f'[{project}/{config}] {line}\n')
        try:
            lines=int(self.log.index('end-1c').split('.')[0])
            if lines>6000:self.log.delete('1.0','1000.0')
        except Exception:pass
        self.log.see('end')
    def refresh_live(self):
        self.live_tree.delete(*self.live_tree.get_children());now=time.time();rows=[]
        for config_id,mp in self.managed.items():rows.append((config_id,mp.project.name,mp.config.name,mp))
        for controller in self.session_controllers.values():
            for sid,mp in controller.processes.items():rows.append((f'{controller.session.id}:{sid}',mp.project.name,mp.config.name,mp))
        for iid,project,name,mp in rows:
            pid=mp.process.pid if mp.process else '';up=fmt_duration(now-mp.started_at) if mp.started_at and mp.running else fmt_duration((mp.ended_at or now)-mp.started_at) if mp.started_at else '—';state='RUNNING' if mp.running else f'EXIT {mp.returncode}';self.live_tree.insert('','end',iid=iid,values=(project,name,pid,up,state))
    def refresh_history(self):
        self.history_tree.delete(*self.history_tree.get_children())
        for record in reversed(self.state.run_history[-250:]):
            started=time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(record.started_at));result='RUNNING' if record.ended_at is None else ('PASS' if record.returncode==0 else f'EXIT {record.returncode}');self.history_tree.insert('','end',iid=record.id,values=(started,record.project_name,record.config_name,result,fmt_duration(record.duration),record.pid or ''))
    def clear_history(self):
        if any(mp.running for mp in self.managed.values()):messagebox.showwarning('Switchyard','Stop running processes before clearing run history.');return
        if messagebox.askyesno('Switchyard','Clear saved run history?'):self.state.run_history.clear();save_state(self.state);self.refresh_history()
    def tick(self):
        self.refresh_live();p=self.current()
        if p:self.refresh_runs(p)
        self.refresh_services();self.refresh_sessions();self.refresh_session_detail();self.after(1000,self.tick)
    def destroy(self):
        for controller in self.session_controllers.values():
            if controller.running:controller.stop()
        for mp in self.managed.values():
            if mp.running:mp.stop()
        save_state(self.state);super().destroy()


if __name__=='__main__':SwitchyardApp().mainloop()
