from __future__ import annotations

import uuid

from switchyard_base import *
from switchyard_runtime import (
    EnvironmentProfile,
    ResilientSessionController,
    RuntimeSettings,
    ServiceRuntimePolicy,
    load_runtime,
    masked_profile_rows,
    policy_for,
    preflight_ok,
    profile_by_id,
    runtime_readiness_description,
    save_runtime,
    session_preflight,
)
from switchyard_core import ReadinessCheck, WorkspaceSession, save_state, service_project, topological_service_order


class ProfileDialog(tk.Toplevel):
    def __init__(self, parent, profile=None):
        super().__init__(parent)
        self.title('Environment profile')
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.result = None
        self.profile = profile

        tk.Label(self, text='ENVIRONMENT PROFILE', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(anchor='w', padx=14, pady=(14, 6))
        name_row = tk.Frame(self, bg=BG); name_row.pack(fill='x', padx=14, pady=5)
        tk.Label(name_row, text='Name', bg=BG, fg=MUTED, width=18, anchor='w').pack(side='left')
        self.name_var = tk.StringVar(value=profile.name if profile else '')
        ttk.Entry(name_row, textvariable=self.name_var, width=48).pack(side='left')

        tk.Label(self, text='Stored non-secret variables  ·  KEY=value', bg=BG, fg=MUTED).pack(anchor='w', padx=14, pady=(10, 4))
        self.values = tk.Text(self, width=70, height=9, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief='flat', font=('Consolas', 10))
        self.values.pack(padx=14)
        if profile:
            self.values.insert('1.0', '\n'.join(f'{k}={v}' for k, v in sorted(profile.variables.items())))

        tk.Label(self, text='Inherited secret/environment keys  ·  names only, one per line', bg=BG, fg=MUTED).pack(anchor='w', padx=14, pady=(10, 4))
        self.inherited = tk.Text(self, width=70, height=7, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief='flat', font=('Consolas', 10))
        self.inherited.pack(padx=14)
        if profile:
            self.inherited.insert('1.0', '\n'.join(profile.inherit_keys))

        note = 'Inherited values are read from the OS environment at launch and are never written into Switchyard runtime.json.'
        tk.Label(self, text=note, bg=BG, fg=CYAN, wraplength=560, justify='left').pack(anchor='w', padx=14, pady=(10, 2))
        buttons = tk.Frame(self, bg=BG); buttons.pack(fill='x', padx=14, pady=14)
        ttk.Button(buttons, text='Cancel', command=self.destroy).pack(side='right', padx=(8, 0))
        ttk.Button(buttons, text='Save profile', style='Accent.TButton', command=self.save).pack(side='right')
        self.bind('<Escape>', lambda _e: self.destroy())

    def save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning('Switchyard', 'Give the profile a name.', parent=self); return
        variables = {}
        for raw in self.values.get('1.0', 'end').splitlines():
            raw = raw.strip()
            if not raw: continue
            if '=' not in raw:
                messagebox.showwarning('Switchyard', f'Invalid variable line: {raw}', parent=self); return
            key, value = raw.split('=', 1); key = key.strip()
            if not key:
                messagebox.showwarning('Switchyard', 'Environment variable names cannot be blank.', parent=self); return
            variables[key] = value
        inherited = []
        for raw in self.inherited.get('1.0', 'end').splitlines():
            key = raw.strip()
            if key and key not in inherited: inherited.append(key)
        overlap = sorted(set(variables) & set(inherited))
        if overlap:
            messagebox.showwarning('Switchyard', 'A key cannot be both stored and inherited:\n' + ', '.join(overlap), parent=self); return
        pid = self.profile.id if self.profile else uuid.uuid4().hex
        self.result = EnvironmentProfile(pid, name, variables, inherited)
        self.destroy()


class PolicyDialog(tk.Toplevel):
    def __init__(self, parent, service, policy, profiles):
        super().__init__(parent)
        self.title(f'Runtime policy — {service.name}')
        self.configure(bg=BG); self.transient(parent); self.grab_set(); self.resizable(False, False)
        self.result = None; self.service = service; self.profiles = profiles
        tk.Label(self, text='SERVICE RUNTIME POLICY', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).grid(row=0, column=0, columnspan=2, sticky='w', padx=14, pady=(14, 8))
        self.restart = tk.StringVar(value=policy.restart)
        self.max_restarts = tk.StringVar(value=str(policy.max_restarts))
        self.base_backoff = tk.StringVar(value=str(policy.base_backoff))
        self.max_backoff = tk.StringVar(value=str(policy.max_backoff))
        names = ['(session profile)'] + [p.name for p in profiles]
        selected_profile = profile_by_id(RuntimeSettings(profiles=profiles), policy.profile_id)
        self.profile_name = tk.StringVar(value=selected_profile.name if selected_profile else '(session profile)')
        rows = [
            ('Restart', ttk.Combobox(self, textvariable=self.restart, values=['never', 'on_failure', 'always'], state='readonly', width=34)),
            ('Max restarts', ttk.Entry(self, textvariable=self.max_restarts, width=37)),
            ('Base backoff (s)', ttk.Entry(self, textvariable=self.base_backoff, width=37)),
            ('Max backoff (s)', ttk.Entry(self, textvariable=self.max_backoff, width=37)),
            ('Environment', ttk.Combobox(self, textvariable=self.profile_name, values=names, state='readonly', width=34)),
        ]
        for i, (label, widget) in enumerate(rows, 1):
            tk.Label(self, text=label, bg=BG, fg=MUTED).grid(row=i, column=0, sticky='w', padx=14, pady=6); widget.grid(row=i, column=1, padx=14, pady=6)
        buttons = tk.Frame(self, bg=BG); buttons.grid(row=7, column=0, columnspan=2, sticky='e', padx=14, pady=14)
        ttk.Button(buttons, text='Cancel', command=self.destroy).pack(side='right', padx=(8, 0)); ttk.Button(buttons, text='Save policy', style='Accent.TButton', command=self.save).pack(side='right')

    def save(self):
        try:
            max_restarts = max(0, int(self.max_restarts.get()))
            base = max(0.0, float(self.base_backoff.get()))
            maximum = max(base, float(self.max_backoff.get()))
        except ValueError:
            messagebox.showwarning('Switchyard', 'Restart limits and backoff values must be numeric.', parent=self); return
        profile_id = None
        if self.profile_name.get() != '(session profile)':
            profile = next((p for p in self.profiles if p.name == self.profile_name.get()), None)
            profile_id = profile.id if profile else None
        self.result = ServiceRuntimePolicy(self.service.id, self.restart.get(), max_restarts, base, maximum, profile_id)
        self.destroy()


class SwitchyardFlagshipApp(SwitchyardApp):
    def __init__(self):
        self.runtime_settings = load_runtime()
        super().__init__()
        self.title('Switchyard — Local Developer Workspace Control Plane')
        self.refresh_runtime()

    def _build(self):
        super()._build()
        self.runtime_tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(self.runtime_tab, text='Runtime')
        self._runtime_panel()

    def _runtime_panel(self):
        header = tk.Frame(self.runtime_tab, bg=BG); header.pack(fill='x', pady=10)
        tk.Label(header, text='RESILIENT RUNTIME', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(side='left')
        tk.Label(header, text='profiles · preflight · HTTP readiness · restart policy', bg=BG, fg=MUTED).pack(side='left', padx=10)
        ttk.Button(header, text='Preflight selected session', style='Accent.TButton', command=self.run_preflight).pack(side='right')

        split = tk.PanedWindow(self.runtime_tab, orient='horizontal', bg='#202733', sashwidth=1); split.pack(fill='both', expand=True)
        left = tk.Frame(split, bg=BG); right = tk.Frame(split, bg=BG); split.add(left, minsize=430); split.add(right, minsize=520)

        profile_bar = tk.Frame(left, bg=BG); profile_bar.pack(fill='x', pady=(0, 5))
        tk.Label(profile_bar, text='ENVIRONMENT PROFILES', bg=BG, fg=CYAN, font=('Segoe UI Semibold', 9)).pack(side='left')
        ttk.Button(profile_bar, text='+', width=3, command=self.add_profile).pack(side='right'); ttk.Button(profile_bar, text='Edit', command=self.edit_profile).pack(side='right', padx=5); ttk.Button(profile_bar, text='Delete', command=self.delete_profile).pack(side='right')
        self.profile_tree = ttk.Treeview(left, columns=('name','stored','inherited'), show='headings', height=7)
        for c,t,w in [('name','PROFILE',180),('stored','STORED',80),('inherited','INHERITED',90)]: self.profile_tree.heading(c,text=t); self.profile_tree.column(c,width=w)
        self.profile_tree.pack(fill='x'); self.profile_tree.bind('<<TreeviewSelect>>', lambda _e:self.refresh_profile_detail())
        self.profile_detail = ttk.Treeview(left, columns=('key','value','source'), show='headings')
        for c,t,w in [('key','KEY',160),('value','VALUE',180),('source','SOURCE',90)]: self.profile_detail.heading(c,text=t); self.profile_detail.column(c,width=w)
        self.profile_detail.pack(fill='both', expand=True, pady=(7,0))

        policy_bar = tk.Frame(right, bg=BG); policy_bar.pack(fill='x', pady=(0,5)); tk.Label(policy_bar,text='SERVICE POLICIES',bg=BG,fg=GREEN,font=('Segoe UI Semibold',9)).pack(side='left'); ttk.Button(policy_bar,text='Edit selected policy',command=self.edit_runtime_policy).pack(side='right'); ttk.Button(policy_bar,text='Set HTTP readiness',command=self.set_http_readiness).pack(side='right',padx=6)
        self.policy_tree = ttk.Treeview(right, columns=('service','restart','attempts','backoff','profile'), show='headings', height=8)
        for c,t,w in [('service','SERVICE',155),('restart','RESTART',95),('attempts','MAX',55),('backoff','BACKOFF',100),('profile','ENV',130)]: self.policy_tree.heading(c,text=t); self.policy_tree.column(c,width=w)
        self.policy_tree.pack(fill='x')

        session_bar = tk.Frame(right,bg=BG);session_bar.pack(fill='x',pady=(10,5));tk.Label(session_bar,text='SESSION ENVIRONMENTS',bg=BG,fg=ORANGE,font=('Segoe UI Semibold',9)).pack(side='left');ttk.Button(session_bar,text='Assign profile',command=self.assign_session_profile).pack(side='right')
        self.runtime_session_tree=ttk.Treeview(right,columns=('session','profile','state'),show='headings',height=6)
        for c,t,w in [('session','SESSION',210),('profile','PROFILE',170),('state','STATE',110)]:self.runtime_session_tree.heading(c,text=t);self.runtime_session_tree.column(c,width=w)
        self.runtime_session_tree.pack(fill='x')

        tk.Label(right,text='PREFLIGHT',bg=BG,fg=GOLD,font=('Segoe UI Semibold',9)).pack(anchor='w',pady=(10,4))
        self.preflight_tree=ttk.Treeview(right,columns=('level','check','detail'),show='headings')
        for c,t,w in [('level','LEVEL',70),('check','CHECK',140),('detail','DETAIL',360)]:self.preflight_tree.heading(c,text=t);self.preflight_tree.column(c,width=w)
        self.preflight_tree.pack(fill='both',expand=True)

    def _selected_profile(self):
        sel=self.profile_tree.selection(); return next((p for p in self.runtime_settings.profiles if sel and p.id==sel[0]),None)

    def add_profile(self):
        dialog=ProfileDialog(self); self.wait_window(dialog)
        if dialog.result:self.runtime_settings.profiles.append(dialog.result);self._save_runtime_refresh(dialog.result.id)

    def edit_profile(self):
        profile=self._selected_profile()
        if not profile:return
        dialog=ProfileDialog(self,profile);self.wait_window(dialog)
        if dialog.result:
            idx=self.runtime_settings.profiles.index(profile);self.runtime_settings.profiles[idx]=dialog.result;self._save_runtime_refresh(dialog.result.id)

    def delete_profile(self):
        profile=self._selected_profile()
        if not profile:return
        in_sessions=[s.name for s in self.state.sessions if self.runtime_settings.session_profiles.get(s.id)==profile.id]
        in_services=[s.name for s in self.state.services if next((p.profile_id for p in self.runtime_settings.policies if p.service_id==s.id),None)==profile.id]
        if in_sessions or in_services:
            messagebox.showwarning('Switchyard','Profile is still assigned.\n\n'+('Sessions: '+', '.join(in_sessions)+'\n' if in_sessions else '')+('Services: '+', '.join(in_services) if in_services else ''));return
        if messagebox.askyesno('Switchyard',f'Delete environment profile “{profile.name}”?'):
            self.runtime_settings.profiles=[p for p in self.runtime_settings.profiles if p.id!=profile.id];self._save_runtime_refresh()

    def _save_runtime_refresh(self,select=None):
        save_runtime(self.runtime_settings);self.refresh_runtime(select)

    def refresh_runtime(self,select=None):
        if not hasattr(self,'profile_tree'):return
        current=select or (self.profile_tree.selection()[0] if self.profile_tree.selection() else None);self.profile_tree.delete(*self.profile_tree.get_children())
        for profile in self.runtime_settings.profiles:self.profile_tree.insert('','end',iid=profile.id,values=(profile.name,len(profile.variables),len(profile.inherit_keys)))
        if current and self.profile_tree.exists(current):self.profile_tree.selection_set(current)
        self.refresh_profile_detail();self.policy_tree.delete(*self.policy_tree.get_children())
        profile_names={p.id:p.name for p in self.runtime_settings.profiles}
        for service in self.state.services:
            policy=next((p for p in self.runtime_settings.policies if p.service_id==service.id),ServiceRuntimePolicy(service.id));profile=profile_names.get(policy.profile_id,'session/default');self.policy_tree.insert('','end',iid=service.id,values=(service.name,policy.restart,policy.max_restarts,f'{policy.base_backoff:g}–{policy.max_backoff:g}s',profile))
        self.runtime_session_tree.delete(*self.runtime_session_tree.get_children())
        for session in self.state.sessions:
            controller=self.session_controllers.get(session.id);state=controller.status if controller else 'IDLE';profile=profile_names.get(self.runtime_settings.session_profiles.get(session.id),'default');self.runtime_session_tree.insert('','end',iid=session.id,values=(session.name,profile,state))

    def refresh_profile_detail(self):
        if not hasattr(self,'profile_detail'):return
        self.profile_detail.delete(*self.profile_detail.get_children());profile=self._selected_profile()
        if profile:
            for i,row in enumerate(masked_profile_rows(profile)):self.profile_detail.insert('','end',iid=f'row-{i}',values=row)

    def edit_runtime_policy(self):
        sel=self.policy_tree.selection();service=next((s for s in self.state.services if sel and s.id==sel[0]),None)
        if not service:return
        policy=policy_for(self.runtime_settings,service.id);dialog=PolicyDialog(self,service,policy,self.runtime_settings.profiles);self.wait_window(dialog)
        if dialog.result:
            self.runtime_settings.policies=[p for p in self.runtime_settings.policies if p.service_id!=service.id];self.runtime_settings.policies.append(dialog.result);self._save_runtime_refresh()

    def assign_session_profile(self):
        sel=self.runtime_session_tree.selection();session=next((s for s in self.state.sessions if sel and s.id==sel[0]),None)
        if not session:return
        choices=['(default)']+[p.name for p in self.runtime_settings.profiles]
        value=simpledialog.askstring('Session environment',f'Profile for {session.name}:\n'+', '.join(choices),initialvalue=profile_by_id(self.runtime_settings,self.runtime_settings.session_profiles.get(session.id)).name if profile_by_id(self.runtime_settings,self.runtime_settings.session_profiles.get(session.id)) else '(default)')
        if value is None:return
        if value.strip()=='(default)':self.runtime_settings.session_profiles.pop(session.id,None)
        else:
            profile=next((p for p in self.runtime_settings.profiles if p.name.lower()==value.strip().lower()),None)
            if not profile:messagebox.showwarning('Switchyard','Profile name not found.');return
            self.runtime_settings.session_profiles[session.id]=profile.id
        self._save_runtime_refresh()

    def set_http_readiness(self):
        sel=self.policy_tree.selection();service=next((s for s in self.state.services if sel and s.id==sel[0]),None)
        if not service:return
        url=simpledialog.askstring('HTTP readiness',f'Health/readiness URL for {service.name}:',initialvalue=service.readiness.target if service.readiness.kind=='http' else 'http://127.0.0.1:8000/health')
        if not url:return
        timeout=simpledialog.askfloat('HTTP readiness','Startup timeout in seconds:',initialvalue=service.readiness.timeout,minvalue=.1)
        if timeout is None:return
        service.readiness=ReadinessCheck('http',url.strip(),timeout);save_state(self.state);self.refresh_services(service.id);self.refresh_runtime();self.refresh_session_detail()

    def _selected_runtime_session(self):
        sel=self.runtime_session_tree.selection();return next((s for s in self.state.sessions if sel and s.id==sel[0]),None)

    def run_preflight(self,session=None,interactive=True):
        session=session or self._selected_runtime_session() or self._selected_session()
        if not session:
            if interactive:messagebox.showinfo('Switchyard','Select a session first.')
            return []
        checks=session_preflight(self.state,session,self.runtime_settings);self.preflight_tree.delete(*self.preflight_tree.get_children())
        for i,check in enumerate(checks):self.preflight_tree.insert('','end',iid=f'pf-{i}',values=(check.level,check.name,check.detail))
        if interactive:
            errors=[c for c in checks if c.level=='ERROR'];warnings=[c for c in checks if c.level=='WARN']
            if errors:messagebox.showerror('Session preflight',f'{len(errors)} blocking problem(s) found. Review the Preflight table.')
            elif warnings:messagebox.showwarning('Session preflight',f'No blockers. {len(warnings)} warning(s) need review.')
            else:messagebox.showinfo('Session preflight','Ready to start. No blocking problems found.')
        return checks

    def start_session(self):
        session=self._selected_session()
        if not session:return
        checks=self.run_preflight(session,interactive=False);errors=[c for c in checks if c.level=='ERROR'];warnings=[c for c in checks if c.level=='WARN']
        if errors:
            self.nb.select(self.runtime_tab);messagebox.showerror('Switchyard',f'Preflight blocked {session.name}. Review {len(errors)} error(s) in Runtime.');return
        if warnings and not messagebox.askyesno('Switchyard',f'Preflight found {len(warnings)} warning(s). Start {session.name} anyway?'):self.nb.select(self.runtime_tab);return
        controller=self.session_controllers.get(session.id)
        if controller and (controller.running or controller.status=='STARTING'):messagebox.showinfo('Switchyard','This session is already active.');return
        controller=ResilientSessionController(self.state,session,self.runtime_settings,on_event=self.on_session_event,on_line=self.on_service_line);self.session_controllers[session.id]=controller
        try:controller.start()
        except Exception as exc:messagebox.showerror('Switchyard',str(exc));return
        save_runtime(self.runtime_settings);self.refresh_sessions(session.id);self.refresh_session_detail();self.refresh_services();self.refresh_runtime();self.nb.select(self.sessions_tab)

    def run_service(self):
        service=self._selected_service()
        if not service:return
        temp=WorkspaceSession('adhoc-'+uuid.uuid4().hex,'Ad-hoc service',[service.id]);controller=ResilientSessionController(self.state,temp,self.runtime_settings,on_event=self.on_session_event,on_line=self.on_service_line);self.session_controllers[temp.id]=controller
        checks=session_preflight(self.state,temp,self.runtime_settings)
        if not preflight_ok(checks):messagebox.showerror('Switchyard','Ad-hoc service preflight failed.');return
        try:controller.start()
        except Exception as exc:messagebox.showerror('Switchyard',str(exc));return
        self.nb.select(self.sessions_tab);self.refresh_sessions();self.refresh_services();self.refresh_runtime()

    def refresh_services(self,select=None):
        super().refresh_services(select)
        if not hasattr(self,'service_tree'):return
        for service in self.state.services:
            if self.service_tree.exists(service.id):
                values=list(self.service_tree.item(service.id,'values'))
                if len(values)>=5:values[4]=runtime_readiness_description(service.readiness);self.service_tree.item(service.id,values=values)
        if hasattr(self,'policy_tree'):self.refresh_runtime()

    def refresh_session_detail(self):
        if not hasattr(self,'session_detail'):return
        self.session_detail.delete('1.0','end');session=self._selected_session()
        if not session:self.session_detail.insert('1.0','Select a workspace session to inspect its topology.');return
        names={s.id:s.name for s in self.state.services};controller=self.session_controllers.get(session.id)
        try:order=topological_service_order(self.state.services,session.service_ids)
        except ValueError as exc:self.session_detail.insert('end',f'GRAPH ERROR\n{exc}\n');return
        self.session_detail.insert('end',f'{session.name.upper()}\n');self.session_detail.insert('end','═'*52+'\n')
        for service in order:
            project=service_project(service,self.state);deps=', '.join(names.get(d,'missing') for d in service.depends_on) or 'none';status=controller.service_status(service.id) if controller else 'IDLE';policy=next((p for p in self.runtime_settings.policies if p.service_id==service.id),ServiceRuntimePolicy(service.id));self.session_detail.insert('end',f'[{status:<9}] {service.name}\n  project   {project.name if project else "missing"}\n  depends   {deps}\n  ready     {runtime_readiness_description(service.readiness)}\n  restart   {policy.restart} ({policy.max_restarts} max)\n  command   {service.command}\n\n')

    def on_session_event(self,event):
        save_runtime(self.runtime_settings);super().on_session_event(event);self.after(0,self.refresh_runtime)

    def tick(self):
        super().tick();self.refresh_runtime()

    def destroy(self):
        save_runtime(self.runtime_settings);super().destroy()


if __name__=='__main__':
    SwitchyardFlagshipApp().mainloop()
