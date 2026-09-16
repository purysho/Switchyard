from __future__ import annotations

import time
from pathlib import Path

from switchyard_phase4 import *
from switchyard_logs import LogStore
from switchyard_topology import (
    SNAPSHOT_DIR,
    begin_recovery_journal,
    clean_recovery_journal,
    export_session_template,
    import_session_snapshot,
    import_session_template,
    list_session_snapshots,
    load_session_snapshot,
    load_session_template,
    port_claims,
    recovery_processes,
    save_session_snapshot,
    terminate_pid_tree,
    topology_layout,
    update_recovery_journal,
)


class SwitchyardPhase5App(SwitchyardFlagshipApp):
    """Phase 5 desktop shell: topology, focused logs, recovery and portability."""

    def __init__(self):
        self.log_store = LogStore()
        self._previous_recovery = begin_recovery_journal()
        self._topology_selected_service = None
        self._topology_refresh_pending = False
        super().__init__()
        self.title('Switchyard — Workspace Control Plane')
        self.after(350, self._offer_crash_recovery)

    def _build(self):
        super()._build()
        self.topology_tab = tk.Frame(self.nb, bg=BG)
        self.logs_tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(self.topology_tab, text='Topology')
        self.nb.add(self.logs_tab, text='Service logs')
        self._topology_panel()
        self._logs_panel()

    # ---------- topology ----------
    def _topology_panel(self):
        bar = tk.Frame(self.topology_tab, bg=BG)
        bar.pack(fill='x', pady=(10, 7))
        tk.Label(bar, text='LIVE WORKSPACE TOPOLOGY', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(side='left')
        self.topology_session_var = tk.StringVar()
        self.topology_session_combo = ttk.Combobox(bar, textvariable=self.topology_session_var, state='readonly', width=28)
        self.topology_session_combo.pack(side='left', padx=10)
        self.topology_session_combo.bind('<<ComboboxSelected>>', lambda _e: self.refresh_topology())
        ttk.Button(bar, text='Refresh', command=self.refresh_topology).pack(side='left')
        ttk.Button(bar, text='Save snapshot', command=self.save_selected_snapshot).pack(side='right', padx=(6, 0))
        ttk.Button(bar, text='Restore snapshot', command=self.restore_snapshot).pack(side='right', padx=(6, 0))
        ttk.Button(bar, text='Import template', command=self.import_template).pack(side='right', padx=(6, 0))
        ttk.Button(bar, text='Export template', command=self.export_template).pack(side='right')

        body = tk.PanedWindow(self.topology_tab, orient='horizontal', bg='#202733', sashwidth=1)
        body.pack(fill='both', expand=True)
        left = tk.Frame(body, bg=BG)
        right = tk.Frame(body, bg=PANEL, width=325)
        body.add(left, minsize=650)
        body.add(right, minsize=275)

        self.topology_canvas = tk.Canvas(left, bg='#080b10', highlightthickness=1, highlightbackground='#222b35')
        self.topology_canvas.pack(fill='both', expand=True)
        self.topology_canvas.bind('<Configure>', self._schedule_topology_refresh)
        self.topology_canvas.bind('<Button-1>', self._on_topology_click)

        tk.Label(right, text='SERVICE INSPECTOR', bg=PANEL, fg=CYAN, font=('Segoe UI Semibold', 9)).pack(anchor='w', padx=14, pady=(14, 6))
        self.topology_detail = tk.Text(right, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief='flat', wrap='word', font=('Consolas', 10), height=18)
        self.topology_detail.pack(fill='both', expand=True, padx=14, pady=(0, 10))
        actions = tk.Frame(right, bg=PANEL)
        actions.pack(fill='x', padx=14, pady=(0, 14))
        ttk.Button(actions, text='Open logs', command=self.open_selected_service_logs).pack(fill='x', pady=(0, 6))
        ttk.Button(actions, text='Runtime policy', command=self.open_selected_runtime_policy).pack(fill='x', pady=(0, 6))
        ttk.Button(actions, text='Stop service', style='Danger.TButton', command=self.stop_topology_service).pack(fill='x')

    def _schedule_topology_refresh(self, _event=None):
        if self._topology_refresh_pending:
            return
        self._topology_refresh_pending = True
        self.after(80, self._run_scheduled_topology_refresh)

    def _run_scheduled_topology_refresh(self):
        self._topology_refresh_pending = False
        self.refresh_topology()

    def _topology_session(self):
        name = self.topology_session_var.get().strip()
        session = next((s for s in self.state.sessions if s.name == name), None)
        return session or self._selected_session()

    def _sync_topology_session_choices(self):
        names = [s.name for s in self.state.sessions]
        self.topology_session_combo['values'] = names
        current = self.topology_session_var.get()
        if current not in names:
            selected = self._selected_session()
            self.topology_session_var.set(selected.name if selected else (names[0] if names else ''))

    def _service_status(self, session, service_id):
        controller = self.session_controllers.get(session.id) if session else None
        return controller.service_status(service_id) if controller else 'IDLE'

    def _status_color(self, status):
        status = status.upper()
        if status == 'READY': return GREEN
        if status == 'STARTING': return GOLD
        if status.startswith('FAILED') or status.startswith('EXIT'): return RED
        return '#66717f'

    def refresh_topology(self):
        if not hasattr(self, 'topology_canvas'):
            return
        self._sync_topology_session_choices()
        canvas = self.topology_canvas
        canvas.delete('all')
        session = self._topology_session()
        if not session:
            canvas.create_text(30, 30, anchor='nw', text='Create a workspace session to see its topology.', fill=MUTED, font=('Segoe UI', 13))
            self._render_topology_detail(None, None)
            return
        try:
            ordered = topological_service_order(self.state.services, session.service_ids)
            width = max(760, canvas.winfo_width())
            height = max(470, canvas.winfo_height())
            nodes, edges = topology_layout(ordered, [s.id for s in ordered], width=width, height=height, padding_x=125, padding_y=70)
        except ValueError as exc:
            canvas.create_text(30, 30, anchor='nw', text=f'GRAPH ERROR\n{exc}', fill=RED, font=('Consolas', 12))
            return

        positions = {node.service_id: node for node in nodes}
        conflict_ids = {sid for claim in port_claims(ordered) if claim.conflict for sid in claim.service_ids}
        for edge in edges:
            source = positions[edge.source_id]; target = positions[edge.target_id]
            x1, y1, x2, y2 = source.x + 92, source.y, target.x - 92, target.y
            mid = (x1 + x2) / 2
            canvas.create_line(x1, y1, mid, y1, mid, y2, x2, y2, fill='#394858', width=2, arrow='last', arrowshape=(8, 10, 4))

        services = {s.id: s for s in ordered}
        projects = {p.id: p.name for p in self.state.projects}
        for node in nodes:
            service = services[node.service_id]
            status = self._service_status(session, service.id)
            outline = RED if service.id in conflict_ids else self._status_color(status)
            x, y = node.x, node.y
            tags = (f'node:{service.id}', 'service-node')
            canvas.create_rectangle(x-92, y-35, x+92, y+35, fill='#11161d', outline=outline, width=2, tags=tags)
            canvas.create_oval(x-79, y-7, x-67, y+5, fill=self._status_color(status), outline='', tags=tags)
            canvas.create_text(x-58, y-13, anchor='w', text=service.name, fill=TEXT, font=('Segoe UI Semibold', 11), tags=tags)
            project = projects.get(service.project_id, 'missing')
            canvas.create_text(x-58, y+11, anchor='w', text=f'{status} · {project}', fill=MUTED, font=('Consolas', 8), tags=tags)
            if service.id in conflict_ids:
                canvas.create_text(x+78, y-24, anchor='e', text='PORT!', fill=RED, font=('Segoe UI Semibold', 8), tags=tags)

        if self._topology_selected_service not in services:
            self._topology_selected_service = ordered[0].id if ordered else None
        service = services.get(self._topology_selected_service)
        self._render_topology_detail(session, service)

    def _on_topology_click(self, event):
        item = self.topology_canvas.find_closest(event.x, event.y)
        if not item:
            return
        for tag in self.topology_canvas.gettags(item[0]):
            if tag.startswith('node:'):
                self._topology_selected_service = tag.split(':', 1)[1]
                self.refresh_topology()
                return

    def _render_topology_detail(self, session, service):
        if not hasattr(self, 'topology_detail'):
            return
        self.topology_detail.delete('1.0', 'end')
        if not service:
            self.topology_detail.insert('1.0', 'Select a service node to inspect it.')
            return
        names = {s.id: s.name for s in self.state.services}
        project = service_project(service, self.state)
        status = self._service_status(session, service.id)
        policy = next((p for p in self.runtime_settings.policies if p.service_id == service.id), ServiceRuntimePolicy(service.id))
        deps = ', '.join(names.get(d, 'missing') for d in service.depends_on) or 'none'
        rows = [
            service.name.upper(), '═' * 34,
            f'State       {status}',
            f'Project     {project.name if project else "missing"}',
            f'Depends     {deps}',
            f'Readiness   {runtime_readiness_description(service.readiness)}',
            f'Restart     {policy.restart} / {policy.max_restarts} max',
            '', 'COMMAND', service.command,
        ]
        self.topology_detail.insert('1.0', '\n'.join(rows))

    def _selected_topology_service(self):
        return next((s for s in self.state.services if s.id == self._topology_selected_service), None)

    def open_selected_service_logs(self):
        service = self._selected_topology_service()
        if not service:
            return
        self.log_service_var.set(service.name)
        self.nb.select(self.logs_tab)
        self.refresh_focused_logs()

    def open_selected_runtime_policy(self):
        service = self._selected_topology_service()
        if not service:
            return
        self.nb.select(self.runtime_tab)
        if self.policy_tree.exists(service.id):
            self.policy_tree.selection_set(service.id)
            self.policy_tree.see(service.id)

    def stop_topology_service(self):
        service = self._selected_topology_service()
        if not service:
            return
        if hasattr(self, 'service_tree') and self.service_tree.exists(service.id):
            self.service_tree.selection_set(service.id)
        self.stop_service()
        self.refresh_topology()

    # ---------- focused logs ----------
    def _logs_panel(self):
        bar = tk.Frame(self.logs_tab, bg=BG); bar.pack(fill='x', pady=(10, 7))
        tk.Label(bar, text='SERVICE LOG STREAMS', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(side='left')
        self.log_service_var = tk.StringVar(value='All services')
        self.log_service_combo = ttk.Combobox(bar, textvariable=self.log_service_var, state='readonly', width=25)
        self.log_service_combo.pack(side='left', padx=(10, 6)); self.log_service_combo.bind('<<ComboboxSelected>>', lambda _e: self.refresh_focused_logs())
        self.log_level_var = tk.StringVar(value='ALL')
        level = ttk.Combobox(bar, textvariable=self.log_level_var, values=['ALL','ERROR','WARN','OK','INFO'], state='readonly', width=8)
        level.pack(side='left', padx=(0, 6)); level.bind('<<ComboboxSelected>>', lambda _e: self.refresh_focused_logs())
        self.log_search_var = tk.StringVar()
        search = ttk.Entry(bar, textvariable=self.log_search_var, width=28); search.pack(side='left', padx=(0, 6)); search.bind('<KeyRelease>', lambda _e: self.refresh_focused_logs())
        self.log_follow_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text='Follow', variable=self.log_follow_var).pack(side='left')
        ttk.Button(bar, text='Export', command=self.export_logs).pack(side='right')
        ttk.Button(bar, text='Clear', command=self.clear_focused_logs).pack(side='right', padx=6)

        self.focus_log = tk.Text(self.logs_tab, bg='#07090c', fg='#cbd5df', insertbackground=TEXT, relief='flat', font=('Consolas', 10), wrap='none')
        self.focus_log.pack(fill='both', expand=True)
        self.focus_log.tag_configure('ERROR', foreground='#ff8b85')
        self.focus_log.tag_configure('WARN', foreground='#efb36b')
        self.focus_log.tag_configure('OK', foreground='#87e1a2')
        self.focus_log.tag_configure('INFO', foreground='#cbd5df')

    def _sync_log_service_choices(self):
        names = ['All services'] + [s.name for s in self.state.services]
        self.log_service_combo['values'] = names
        if self.log_service_var.get() not in names:
            self.log_service_var.set('All services')

    def _focused_service_id(self):
        name = self.log_service_var.get()
        service = next((s for s in self.state.services if s.name == name), None)
        return service.id if service else None

    def refresh_focused_logs(self):
        if not hasattr(self, 'focus_log'):
            return
        self._sync_log_service_choices()
        level = self.log_level_var.get()
        levels = None if level == 'ALL' else [level]
        rows = self.log_store.query(self._focused_service_id(), self.log_search_var.get(), levels, limit=4000)
        self.focus_log.delete('1.0', 'end')
        for row in rows:
            stamp = time.strftime('%H:%M:%S', time.localtime(row.timestamp))
            self.focus_log.insert('end', f'{stamp}  {row.service_name:<18}  {row.line}\n', row.level)
        if self.log_follow_var.get():
            self.focus_log.see('end')

    def export_logs(self):
        path = filedialog.asksaveasfilename(title='Export Switchyard logs', defaultextension='.log', filetypes=[('Log file','*.log'),('Text file','*.txt'),('All files','*.*')])
        if not path:
            return
        level = self.log_level_var.get(); levels = None if level == 'ALL' else [level]
        try:
            self.log_store.export_text(path, self._focused_service_id(), self.log_search_var.get(), levels)
        except OSError as exc:
            messagebox.showerror('Switchyard', f'Could not export logs:\n{exc}')

    def clear_focused_logs(self):
        sid = self._focused_service_id()
        self.log_store.clear(sid)
        self.refresh_focused_logs()

    def on_service_line(self, service, line):
        project = service_project(service, self.state)
        self.log_store.add(service.id, service.name, project.name if project else 'missing', line)
        super().on_service_line(service, line)
        if hasattr(self, 'focus_log') and self.log_follow_var.get():
            self.after(0, self.refresh_focused_logs)

    # ---------- snapshots/templates ----------
    def _template_project_map(self, data):
        projects = sorted({str(item.get('project','')).strip() for item in data.get('services', []) if str(item.get('project','')).strip()})
        existing = {p.name.lower(): p for p in self.state.projects}
        mapping = {}
        for name in projects:
            if name.lower() in existing:
                continue
            answer = simpledialog.askstring('Map project', f'Template project “{name}” is not registered.\n\nType the name of an existing Switchyard project to map it to:')
            if answer is None:
                raise ValueError('Import cancelled')
            project = next((p for p in self.state.projects if p.name.lower() == answer.strip().lower()), None)
            if not project:
                raise ValueError(f'No registered project named {answer!r}')
            mapping[name] = project.id
        return mapping

    def import_template(self):
        path = filedialog.askopenfilename(title='Import Switchyard session template', filetypes=[('Switchyard session','*.json'),('JSON','*.json')])
        if not path:
            return
        try:
            data = load_session_template(path)
            mapping = self._template_project_map(data)
            session, services = import_session_template(self.state, data, project_map=mapping)
            self.state.services.extend(services); self.state.sessions.append(session); save_state(self.state)
            self.refresh_services(); self.refresh_sessions(session.id); self.topology_session_var.set(session.name); self.refresh_topology()
            messagebox.showinfo('Switchyard', f'Imported {session.name} with {len(services)} service(s).')
        except ValueError as exc:
            if str(exc) != 'Import cancelled': messagebox.showerror('Switchyard', str(exc))

    def export_template(self):
        session = self._topology_session()
        if not session:
            messagebox.showinfo('Switchyard', 'Select a session first.'); return
        path = filedialog.asksaveasfilename(title='Export Switchyard session template', initialfile=f'{session.name}.switchyard.json', defaultextension='.json', filetypes=[('JSON','*.json')])
        if not path: return
        try:
            export_session_template(self.state, session, path); messagebox.showinfo('Switchyard', 'Session template exported. Environment values were not included.')
        except (ValueError, OSError) as exc: messagebox.showerror('Switchyard', str(exc))

    def _snapshot_runtime_metadata(self, session):
        profile_names = {p.id:p.name for p in self.runtime_settings.profiles}
        service_names = {s.id:s.name for s in self.state.services}
        policies = {}
        for policy in self.runtime_settings.policies:
            if policy.service_id in service_names:
                policies[service_names[policy.service_id]] = {
                    'restart': policy.restart,
                    'max_restarts': policy.max_restarts,
                    'base_backoff': policy.base_backoff,
                    'max_backoff': policy.max_backoff,
                    'profile': profile_names.get(policy.profile_id),
                }
        return {'session_profile': profile_names.get(self.runtime_settings.session_profiles.get(session.id)), 'policies': policies}

    def save_selected_snapshot(self):
        session = self._topology_session()
        if not session: messagebox.showinfo('Switchyard','Select a session first.'); return
        try:
            path = save_session_snapshot(self.state, session, self._snapshot_runtime_metadata(session))
            messagebox.showinfo('Switchyard', f'Snapshot saved:\n{path}')
        except (ValueError,OSError) as exc: messagebox.showerror('Switchyard', str(exc))

    def restore_snapshot(self):
        path = filedialog.askopenfilename(title='Restore Switchyard snapshot', initialdir=str(SNAPSHOT_DIR), filetypes=[('Switchyard snapshot','*.json'),('JSON','*.json')])
        if not path: return
        try:
            snapshot = load_session_snapshot(path)
            mapping = self._template_project_map(snapshot['session'])
            session, services, metadata = import_session_snapshot(self.state, snapshot, project_map=mapping)
            self.state.services.extend(services); self.state.sessions.append(session)
            profile_by_name = {p.name.lower():p for p in self.runtime_settings.profiles}
            service_by_name = {s.name:s for s in services}
            session_profile_name = metadata.get('session_profile')
            if session_profile_name and session_profile_name.lower() in profile_by_name:
                self.runtime_settings.session_profiles[session.id] = profile_by_name[session_profile_name.lower()].id
            for name, raw in (metadata.get('policies') or {}).items():
                service = service_by_name.get(name)
                if not service: continue
                profile = profile_by_name.get(str(raw.get('profile') or '').lower())
                self.runtime_settings.policies.append(ServiceRuntimePolicy(service.id, raw.get('restart','never'), int(raw.get('max_restarts',3)), float(raw.get('base_backoff',1)), float(raw.get('max_backoff',8)), profile.id if profile else None))
            save_state(self.state); save_runtime(self.runtime_settings)
            self.refresh_services(); self.refresh_sessions(session.id); self.refresh_runtime(); self.topology_session_var.set(session.name); self.refresh_topology()
            messagebox.showinfo('Switchyard', f'Restored snapshot as {session.name}.')
        except (ValueError,OSError) as exc: messagebox.showerror('Switchyard', str(exc))

    # ---------- crash recovery journal ----------
    def _session_process_map(self, session):
        controller = self.session_controllers.get(session.id) if session else None
        if not controller: return {}
        rows = {}
        for sid, managed in controller.processes.items():
            if managed.process and managed.running: rows[sid] = managed.process.pid
        return rows

    def _sync_recovery_journal(self):
        active = None
        for session in self.state.sessions:
            controller = self.session_controllers.get(session.id)
            if controller and (controller.running or controller.status == 'STARTING'):
                active = session; break
        update_recovery_journal(active, self._session_process_map(active) if active else {})

    def _offer_crash_recovery(self):
        marker = self._previous_recovery
        if not marker or not marker.get('active_session_id'):
            return
        session = next((s for s in self.state.sessions if s.id == marker.get('active_session_id')), None)
        rows = recovery_processes(marker); alive = [row for row in rows if row.alive]
        label = marker.get('active_session_name') or 'previous session'
        if not session:
            messagebox.showwarning('Switchyard recovery', f'Switchyard detected an unclean previous run for {label}, but that session no longer exists. The recovery marker will be forgotten.')
            return
        if alive:
            choice = messagebox.askyesnocancel('Switchyard recovery', f'The previous run ended while “{label}” was active.\n\n{len(alive)} recorded process(es) are still alive.\n\nYes — stop those orphan processes and restart the session\nNo — leave them alone and forget recovery\nCancel — leave them alone and inspect the workspace')
            if choice is True:
                failed = [row.pid for row in alive if not terminate_pid_tree(row.pid)]
                if failed:
                    messagebox.showerror('Switchyard recovery', 'Could not stop PID(s): ' + ', '.join(map(str, failed))); return
                self._select_and_start_recovery_session(session)
            return
        if messagebox.askyesno('Switchyard recovery', f'The previous run ended while “{label}” was active, but no recorded process is still running.\n\nRestore that session now?'):
            self._select_and_start_recovery_session(session)

    def _select_and_start_recovery_session(self, session):
        if self.session_tree.exists(session.id):
            self.session_tree.selection_set(session.id); self.session_tree.see(session.id)
        self.topology_session_var.set(session.name)
        self.start_session()

    def on_session_event(self, event):
        super().on_session_event(event)
        self.after(0, self._sync_recovery_journal)
        self.after(0, self.refresh_topology)

    def start_session(self):
        super().start_session(); self.after(250, self._sync_recovery_journal); self.after(250, self.refresh_topology)

    def stop_session(self):
        super().stop_session(); self.after(350, self._sync_recovery_journal); self.after(350, self.refresh_topology)

    def refresh_sessions(self, select=None):
        super().refresh_sessions(select)
        if hasattr(self, 'topology_session_combo'):
            self._sync_topology_session_choices()

    def tick(self):
        super().tick()
        self.refresh_topology()
        if hasattr(self, 'focus_log') and self.log_follow_var.get(): self.refresh_focused_logs()

    def destroy(self):
        try:
            super().destroy()
        finally:
            clean_recovery_journal()


if __name__ == '__main__':
    SwitchyardPhase5App().mainloop()
