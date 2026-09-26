from __future__ import annotations

import threading
import time
from pathlib import Path

from switchyard_phase6 import *
from switchyard_daily_model import PaletteItem, dashboard_summary, rank_palette


class CommandPalette(tk.Toplevel):
    def __init__(self, parent, items, actions):
        super().__init__(parent)
        self.parent = parent; self.items = list(items); self.actions = actions; self.filtered = []
        self.title('Switchyard command palette'); self.configure(bg=BG); self.transient(parent)
        self.geometry('720x470'); self.minsize(560,360)
        self.query = tk.StringVar()
        box = tk.Frame(self, bg=BG); box.pack(fill='both', expand=True, padx=14, pady=14)
        tk.Label(box, text='COMMAND PALETTE', bg=BG, fg=GOLD, font=('Segoe UI Semibold',9)).pack(anchor='w', pady=(0,7))
        self.entry = ttk.Entry(box, textvariable=self.query, font=('Segoe UI',13)); self.entry.pack(fill='x'); self.entry.focus_set()
        self.listbox = tk.Listbox(box, bg=PANEL, fg=TEXT, selectbackground='#26384a', highlightthickness=0, borderwidth=0, font=('Segoe UI',11), activestyle='none')
        self.listbox.pack(fill='both', expand=True, pady=(9,0))
        self.hint = tk.Label(box, text='', bg=BG, fg=MUTED, anchor='w', justify='left'); self.hint.pack(fill='x', pady=(7,0))
        self.query.trace_add('write', lambda *_: self.refresh())
        self.listbox.bind('<<ListboxSelect>>', lambda _e:self._show_hint())
        self.listbox.bind('<Double-1>', lambda _e:self.execute())
        self.bind('<Return>', lambda _e:self.execute()); self.bind('<Escape>', lambda _e:self.destroy())
        self.bind('<Down>', self._down); self.bind('<Up>', self._up)
        self.refresh(); self.grab_set()

    def refresh(self):
        self.filtered = rank_palette(self.items, self.query.get())
        self.listbox.delete(0,'end')
        for item in self.filtered: self.listbox.insert('end', item.label)
        if self.filtered: self.listbox.selection_set(0)
        self._show_hint()

    def _show_hint(self):
        selection = self.listbox.curselection()
        self.hint.configure(text=self.filtered[selection[0]].hint if selection and selection[0] < len(self.filtered) else '')

    def _down(self, _event):
        if not self.filtered: return 'break'
        current = self.listbox.curselection()[0] if self.listbox.curselection() else -1
        target = min(len(self.filtered)-1, current+1); self.listbox.selection_clear(0,'end'); self.listbox.selection_set(target); self.listbox.see(target); self._show_hint(); return 'break'

    def _up(self, _event):
        if not self.filtered: return 'break'
        current = self.listbox.curselection()[0] if self.listbox.curselection() else 1
        target = max(0, current-1); self.listbox.selection_clear(0,'end'); self.listbox.selection_set(target); self.listbox.see(target); self._show_hint(); return 'break'

    def execute(self):
        selection = self.listbox.curselection()
        if not selection or selection[0] >= len(self.filtered): return
        item = self.filtered[selection[0]]; action = self.actions.get(item.id); self.destroy()
        if action: self.parent.after(1, action)


class SwitchyardDailyApp(SwitchyardPhase6App):
    def __init__(self):
        self._dashboard_busy = False; self._last_dashboard_refresh = 0.0; self._dashboard_generation = 0
        super().__init__()
        self.title('Switchyard — Local Development Workspace Control Plane')
        self.bind_all('<Control-k>', lambda _e:self.open_command_palette())
        self.bind_all('<Control-1>', lambda _e:self._select_tab('Dashboard'))
        self.bind_all('<Control-2>', lambda _e:self._select_tab('Topology'))
        self.bind_all('<Control-3>', lambda _e:self._select_tab('Service logs'))
        self.bind_all('<Control-4>', lambda _e:self._select_tab('Runtime'))
        self.bind_all('<Control-5>', lambda _e:self._select_tab('Ecosystem'))
        self.after(180, self.refresh_dashboard)

    def _build(self):
        super()._build()
        self.dashboard_tab = tk.Frame(self.nb, bg=BG)
        self.nb.insert(0, self.dashboard_tab, text='Dashboard')
        self._dashboard_panel()
        self.notice_var = tk.StringVar(value='Ready.')
        notice = tk.Label(self.content, textvariable=self.notice_var, bg='#0d1218', fg=MUTED, anchor='w', padx=12, pady=5, font=('Consolas',9))
        notice.pack(fill='x', padx=18, pady=(0,8), before=self.nb)

    def _dashboard_panel(self):
        hero = tk.Frame(self.dashboard_tab, bg=BG); hero.pack(fill='x', pady=(12,10))
        left = tk.Frame(hero,bg=BG); left.pack(side='left',fill='x',expand=True)
        tk.Label(left,text='WORKSPACE DASHBOARD',bg=BG,fg=GOLD,font=('Segoe UI Semibold',9)).pack(anchor='w')
        tk.Label(left,text='Your local development day at a glance.',bg=BG,fg=TEXT,font=('Segoe UI Semibold',20)).pack(anchor='w',pady=(3,0))
        self.dashboard_subtitle=tk.Label(left,text='Refreshing…',bg=BG,fg=MUTED);self.dashboard_subtitle.pack(anchor='w',pady=(4,0))
        actions=tk.Frame(hero,bg=BG);actions.pack(side='right')
        ttk.Button(actions,text='⌘  Command palette',command=self.open_command_palette).pack(side='right',padx=(7,0))
        ttk.Button(actions,text='Start last workspace',style='Accent.TButton',command=self.start_last_workspace).pack(side='right')

        cards=tk.Frame(self.dashboard_tab,bg=BG);cards.pack(fill='x',pady=(0,12));self.dashboard_cards={}
        for key,label in [('projects','PROJECTS'),('dirty','DIRTY REPOS'),('sessions','LIVE SESSIONS'),('services','READY SERVICES'),('ports','PORT CONFLICTS')]:
            card=tk.Frame(cards,bg=PANEL,highlightbackground='#222b35',highlightthickness=1);card.pack(side='left',fill='both',expand=True,padx=3)
            value=tk.Label(card,text='—',bg=PANEL,fg=TEXT,font=('Segoe UI Semibold',18));value.pack(anchor='w',padx=11,pady=(9,0));tk.Label(card,text=label,bg=PANEL,fg=MUTED,font=('Segoe UI Semibold',8)).pack(anchor='w',padx=11,pady=(1,9));self.dashboard_cards[key]=value

        split=tk.PanedWindow(self.dashboard_tab,orient='horizontal',bg='#202733',sashwidth=1);split.pack(fill='both',expand=True)
        left=tk.Frame(split,bg=BG);right=tk.Frame(split,bg=BG);split.add(left,minsize=560);split.add(right,minsize=360)
        tk.Label(left,text='RECENT + PINNED PROJECTS',bg=BG,fg=CYAN,font=('Segoe UI Semibold',9)).pack(anchor='w',pady=(0,5))
        self.dashboard_projects=ttk.Treeview(left,columns=('state','branch','changes','path'),show='tree headings',height=8)
        self.dashboard_projects.heading('#0',text='PROJECT');self.dashboard_projects.column('#0',width=185)
        for c,t,w in [('state','STATE',80),('branch','BRANCH',120),('changes','CHANGES',80),('path','PATH',320)]:self.dashboard_projects.heading(c,text=t);self.dashboard_projects.column(c,width=w)
        self.dashboard_projects.pack(fill='both',expand=True);self.dashboard_projects.bind('<Double-1>',lambda _e:self.open_dashboard_project())
        tk.Label(left,text='WORKSPACE SESSIONS',bg=BG,fg=GREEN,font=('Segoe UI Semibold',9)).pack(anchor='w',pady=(12,5))
        self.dashboard_sessions=ttk.Treeview(left,columns=('state','services'),show='tree headings',height=6);self.dashboard_sessions.heading('#0',text='SESSION');self.dashboard_sessions.column('#0',width=260)
        self.dashboard_sessions.heading('state',text='STATE');self.dashboard_sessions.column('state',width=110);self.dashboard_sessions.heading('services',text='SERVICES');self.dashboard_sessions.column('services',width=90)
        self.dashboard_sessions.pack(fill='x');self.dashboard_sessions.bind('<Double-1>',lambda _e:self.start_dashboard_session())

        tk.Label(right,text='ATTENTION',bg=BG,fg=ORANGE,font=('Segoe UI Semibold',9)).pack(anchor='w',pady=(0,5))
        self.attention_list=tk.Listbox(right,bg=PANEL,fg=TEXT,selectbackground='#26384a',highlightthickness=0,borderwidth=0,font=('Segoe UI',10),activestyle='none');self.attention_list.pack(fill='both',expand=True)
        tk.Label(right,text='QUICK ACTIONS',bg=BG,fg=GOLD,font=('Segoe UI Semibold',9)).pack(anchor='w',pady=(12,5))
        quick=tk.Frame(right,bg=BG);quick.pack(fill='x')
        # Two by two, so the last action is not clipped when the column is narrow.
        for i,(text,command) in enumerate([('Topology',lambda:self._select_tab('Topology')),('Logs',lambda:self._select_tab('Service logs')),('Runtime',lambda:self._select_tab('Runtime')),('Ecosystem',lambda:self._select_tab('Ecosystem'))]):ttk.Button(quick,text=text,command=command).grid(row=i//2,column=i%2,sticky='ew',padx=(0,6) if i%2==0 else 0,pady=(0,6))
        quick.columnconfigure(0,weight=1,uniform='quick');quick.columnconfigure(1,weight=1,uniform='quick')

    def _collect_dashboard_statuses(self):
        sessions={};services={}
        priority={'FAILED':5,'DEGRADED':4,'STARTING':3,'READY':2,'RUNNING':2,'IDLE':0,'STOPPED':0}
        for session in self.state.sessions:
            controller=self.session_controllers.get(session.id);sessions[session.id]=controller.status if controller else 'IDLE'
            if controller:
                for service in self.state.services:
                    status=controller.service_status(service.id)
                    if priority.get(status.split(':',1)[0],1) >= priority.get(services.get(service.id,'IDLE').split(':',1)[0],0):services[service.id]=status
        return sessions,services

    def refresh_dashboard(self, force=False):
        if not hasattr(self,'dashboard_projects') or self._dashboard_busy:return
        if not force and time.monotonic()-self._last_dashboard_refresh<5:return
        self._dashboard_busy=True;self._dashboard_generation+=1;generation=self._dashboard_generation;sessions,services=self._collect_dashboard_statuses()
        def work():
            try:summary=dashboard_summary(self.state,sessions,services);error=None
            except Exception as exc:summary=None;error=exc
            self.after(0,lambda:self._render_dashboard(generation,summary,error,sessions))
        threading.Thread(target=work,daemon=True).start()

    def _render_dashboard(self,generation,summary,error,session_statuses):
        if generation!=self._dashboard_generation:return
        self._dashboard_busy=False;self._last_dashboard_refresh=time.monotonic()
        if error:self.dashboard_subtitle.configure(text=f'Dashboard refresh failed: {error}',fg=RED);return
        self.dashboard_subtitle.configure(text=f'{len(summary.projects)} projects · {summary.total_services} services · local-only control plane',fg=MUTED)
        values={'projects':len(summary.projects),'dirty':summary.dirty_count,'sessions':summary.running_sessions,'services':f'{summary.ready_services}/{summary.total_services}','ports':len(summary.port_conflicts)}
        for key,value in values.items():self.dashboard_cards[key].configure(text=str(value),fg=RED if key in {'dirty','ports'} and int(value)>0 else TEXT)
        self.dashboard_projects.delete(*self.dashboard_projects.get_children())
        for row in summary.projects:
            state='MISSING' if not row.exists else ('DIRTY' if row.dirty else 'OK');marker='★ ' if row.pinned else ''
            self.dashboard_projects.insert('','end',iid=row.id,text=marker+row.name,values=(state,row.branch or '—',row.changed or '—',row.path))
        self.dashboard_sessions.delete(*self.dashboard_sessions.get_children())
        for session in self.state.sessions:self.dashboard_sessions.insert('','end',iid=session.id,text=session.name,values=(session_statuses.get(session.id,'IDLE'),len(session.service_ids)))
        self.attention_list.delete(0,'end')
        if summary.attention:
            for line in summary.attention:self.attention_list.insert('end','• '+line)
        else:self.attention_list.insert('end','✓ Nothing needs immediate attention.')

    def _select_project_id(self,project_id,open_overview=False):
        self.state.selected_project=project_id;save_state(self.state);self.refresh_projects(project_id)
        if open_overview:self._select_tab('Overview')

    def open_dashboard_project(self):
        sel=self.dashboard_projects.selection()
        if sel:self._select_project_id(sel[0],True)

    def start_dashboard_session(self):
        sel=self.dashboard_sessions.selection()
        if not sel:return
        if self.session_tree.exists(sel[0]):self.session_tree.selection_set(sel[0]);self.session_tree.see(sel[0])
        self.start_session();self.refresh_dashboard(True)

    def _last_session(self):
        for event in reversed(self.state.session_history):
            session=next((s for s in self.state.sessions if s.id==event.session_id),None)
            if session:return session
        return self.state.sessions[0] if self.state.sessions else None

    def start_last_workspace(self):
        session=self._last_session()
        if not session:messagebox.showinfo('Switchyard','Create a workspace session first.');return
        if self.session_tree.exists(session.id):self.session_tree.selection_set(session.id);self.session_tree.see(session.id)
        self.start_session();self.notify(f'Starting {session.name}…');self.refresh_dashboard(True)

    def _select_tab(self,title):
        for tab_id in self.nb.tabs():
            if self.nb.tab(tab_id,'text')==title:self.nb.select(tab_id);return

    def _palette_commands(self):
        items=[];actions={}
        def add(pid,label,hint,action,*keywords):items.append(PaletteItem(pid,label,hint,tuple(keywords)));actions[pid]=action
        for title in ['Dashboard','Overview','Intelligence','Run configurations','Services','Sessions','Topology','Service logs','Runtime','Ecosystem','History','Live processes']:
            add('tab:'+title,f'Go to {title}',f'Open the {title} view',lambda t=title:self._select_tab(t),'view','tab')
        for project in self.state.projects:
            add('project:'+project.id,f'Open project · {project.name}',project.path,lambda p=project.id:self._select_project_id(p,True),'project',*project.tags)
        for session in self.state.sessions:
            add('start:'+session.id,f'Start session · {session.name}','Preflight and start its service graph',lambda s=session.id:self._palette_start_session(s),'start','workspace','session')
            add('stop:'+session.id,f'Stop session · {session.name}','Stop its services in reverse dependency order',lambda s=session.id:self._palette_stop_session(s),'stop','workspace','session')
            add('preflight:'+session.id,f'Preflight · {session.name}','Check commands, environment, readiness and ports',lambda s=session.id:self._palette_preflight(s),'check','session')
        add('handoff:blackbox','Handoff · BLACKBOX','Inspect the selected project repository',self.handoff_blackbox,'inspect','repository')
        add('handoff:needle','Handoff · Needle','Search the selected project workspace',self.handoff_needle,'search','files')
        add('handoff:relay','Handoff · Relay','Inspect the selected service endpoint',self.handoff_relay,'http','api')
        add('handoff:pulse','Handoff · Pulse','Inspect the selected service process',self.handoff_pulse,'process','network')
        add('refresh:dashboard','Refresh dashboard','Recompute workspace health and Git state',lambda:self.refresh_dashboard(True),'refresh','health')
        return items,actions

    def open_command_palette(self):
        items,actions=self._palette_commands();CommandPalette(self,items,actions)

    def _palette_select_session(self,session_id):
        if self.session_tree.exists(session_id):self.session_tree.selection_set(session_id);self.session_tree.see(session_id);return True
        return False

    def _palette_start_session(self,session_id):
        if self._palette_select_session(session_id):self.start_session();self.notify('Session start requested.');self.refresh_dashboard(True)

    def _palette_stop_session(self,session_id):
        if self._palette_select_session(session_id):self.stop_session();self.notify('Session stop requested.');self.refresh_dashboard(True)

    def _palette_preflight(self,session_id):
        if self._palette_select_session(session_id):self.run_preflight();self._select_tab('Runtime')

    def notify(self,text,seconds=4):
        if not hasattr(self,'notice_var'):return
        self.notice_var.set(text)
        marker=text
        self.after(int(seconds*1000),lambda:self.notice_var.set('Ready.') if self.notice_var.get()==marker else None)

    def on_session_event(self,event):
        super().on_session_event(event)
        important={'session-ready':'Workspace ready.','service-failed':'Service failed.','restart-failed':'Service restart failed.','session-degraded':'Workspace degraded.','preflight-error':'Preflight failed.'}
        if event.kind in important:self.notify(f'{important[event.kind]} {event.message}')
        self.after(80,lambda:self.refresh_dashboard(True))

    def refresh_projects(self,select=None):
        super().refresh_projects(select)
        if hasattr(self,'dashboard_projects'):self.refresh_dashboard(True)

    def tick(self):
        super().tick();self.refresh_dashboard(False)


if __name__ == '__main__':
    SwitchyardDailyApp().mainloop()
