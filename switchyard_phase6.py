from __future__ import annotations

from switchyard_phase5 import *
from switchyard_integrations import TOOLS, discover_tool, handoff_args, launch_tool, open_tool_repository, readiness_url
from switchyard_topology import acknowledge_recovery_journal


class SwitchyardPhase6App(SwitchyardPhase5App):
    def _build(self):
        super()._build()
        self.ecosystem_tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(self.ecosystem_tab, text='Ecosystem')
        self._ecosystem_panel()
        self.bind_all('<Control-Shift-b>', lambda _e: self.handoff_blackbox())
        self.bind_all('<Control-Shift-n>', lambda _e: self.handoff_needle())
        self.bind_all('<Control-Shift-r>', lambda _e: self.handoff_relay())
        self.bind_all('<Control-Shift-p>', lambda _e: self.handoff_pulse())

    def _ecosystem_panel(self):
        header = tk.Frame(self.ecosystem_tab, bg=BG); header.pack(fill='x', pady=(12, 8))
        tk.Label(header, text='PURYSHO HANDOFFS', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(side='left')
        tk.Label(header, text='Switchyard coordinates. Specialized tools inspect deeper.', bg=BG, fg=MUTED).pack(side='left', padx=10)
        ttk.Button(header, text='Refresh availability', command=self.refresh_ecosystem).pack(side='right')

        self.ecosystem_context = tk.Label(self.ecosystem_tab, bg=PANEL, fg=TEXT, justify='left', anchor='w', padx=14, pady=12, font=('Consolas', 10))
        self.ecosystem_context.pack(fill='x', pady=(0, 12))
        grid = tk.Frame(self.ecosystem_tab, bg=BG); grid.pack(fill='both', expand=True)
        self.tool_status = {}
        cards = [
            ('blackbox', 'BLACKBOX', 'Repository intelligence', 'Inspect the selected project’s structure, hotspots, dependencies, and suspicious patterns.', self.handoff_blackbox, 'Ctrl+Shift+B'),
            ('needle', 'Needle', 'Workspace search', 'Build a local handoff index for the selected project and search its files without uploading them.', self.handoff_needle, 'Ctrl+Shift+N'),
            ('relay', 'Relay', 'Endpoint inspection', 'Open the selected service readiness endpoint in Relay for HTTP request/response inspection.', self.handoff_relay, 'Ctrl+Shift+R'),
            ('pulse', 'Pulse', 'Process inspection', 'Open the selected running service process in Pulse to inspect process and TCP relationships.', self.handoff_pulse, 'Ctrl+Shift+P'),
        ]
        for i, (key, name, subtitle, text, command, shortcut) in enumerate(cards):
            card = tk.Frame(grid, bg=PANEL, highlightbackground='#222b35', highlightthickness=1)
            card.grid(row=i//2, column=i%2, sticky='nsew', padx=6, pady=6)
            tk.Label(card, text=name, bg=PANEL, fg=TEXT, font=('Segoe UI Semibold', 20)).pack(anchor='w', padx=16, pady=(16, 2))
            tk.Label(card, text=subtitle.upper(), bg=PANEL, fg=CYAN if key in {'relay','pulse'} else GOLD, font=('Segoe UI Semibold', 8)).pack(anchor='w', padx=16)
            tk.Label(card, text=text, bg=PANEL, fg=MUTED, wraplength=420, justify='left').pack(anchor='w', padx=16, pady=(10, 12))
            status = tk.Label(card, text='Checking…', bg=PANEL, fg=MUTED, font=('Consolas', 9)); status.pack(anchor='w', padx=16, pady=(0, 10)); self.tool_status[key] = status
            buttons = tk.Frame(card, bg=PANEL); buttons.pack(fill='x', padx=16, pady=(0, 16))
            ttk.Button(buttons, text='Handoff', style='Accent.TButton', command=command).pack(side='left')
            ttk.Button(buttons, text='Repository', command=lambda k=key: open_tool_repository(k)).pack(side='left', padx=7)
            tk.Label(buttons, text=shortcut, bg=PANEL, fg=MUTED, font=('Consolas', 8)).pack(side='right')
        grid.grid_columnconfigure(0, weight=1); grid.grid_columnconfigure(1, weight=1); grid.grid_rowconfigure(0, weight=1); grid.grid_rowconfigure(1, weight=1)
        self.refresh_ecosystem()

    def _project_paths(self):
        return [project.path for project in self.state.projects]

    def refresh_ecosystem(self):
        if not hasattr(self, 'tool_status'): return
        project = self.current(); service = self._selected_topology_service()
        session = self._topology_session() if hasattr(self, 'topology_session_var') else None
        pid = self._service_pid(service.id) if service else None
        endpoint = readiness_url(service.readiness) if service else None
        self.ecosystem_context.configure(text=(
            f'PROJECT   {project.name if project else "none selected"}\n'
            f'SERVICE   {service.name if service else "none selected in Topology"}\n'
            f'ENDPOINT  {endpoint or "not available"}\n'
            f'PID       {pid or "not running"}'
        ))
        for key, label in self.tool_status.items():
            launch = discover_tool(key, self._project_paths())
            if launch:
                label.configure(text=f'AVAILABLE · {launch.mode} · {launch.location}', fg=GREEN)
            else:
                label.configure(text='NOT FOUND LOCALLY · repository link available', fg=ORANGE)

    def _service_pid(self, service_id):
        if not service_id: return None
        for controller in self.session_controllers.values():
            managed = controller.processes.get(service_id)
            if managed and managed.process and managed.running:
                return managed.process.pid
        return None

    def _launch_or_offer(self, key, args):
        try:
            launch = launch_tool(key, args, self._project_paths())
            self.append_log('ECOSYSTEM', TOOLS[key].name, f'Handoff launched via {launch.mode}: {launch.location}')
            self.refresh_ecosystem()
            return True
        except FileNotFoundError:
            if messagebox.askyesno('Switchyard', f'{TOOLS[key].name} was not found locally. Open its GitHub repository?'):
                open_tool_repository(key)
            return False
        except OSError as exc:
            messagebox.showerror('Switchyard', f'Could not launch {TOOLS[key].name}:\n{exc}')
            return False

    def handoff_blackbox(self):
        project = self.current()
        if not project: messagebox.showinfo('Switchyard', 'Select a project first.'); return
        self._launch_or_offer('blackbox', handoff_args('blackbox', project_path=project.path))

    def handoff_needle(self):
        project = self.current()
        if not project: messagebox.showinfo('Switchyard', 'Select a project first.'); return
        query = simpledialog.askstring('Needle handoff', 'Optional search query:', parent=self) or ''
        self._launch_or_offer('needle', handoff_args('needle', project_path=project.path, query=query))

    def handoff_relay(self):
        service = self._selected_topology_service()
        if not service: messagebox.showinfo('Switchyard', 'Select a service in Topology first.'); return
        args = handoff_args('relay', service=service)
        if not args:
            messagebox.showinfo('Switchyard', 'This service has no HTTP or TCP readiness endpoint to hand to Relay.'); return
        self._launch_or_offer('relay', args)

    def handoff_pulse(self):
        service = self._selected_topology_service()
        if not service: messagebox.showinfo('Switchyard', 'Select a running service in Topology first.'); return
        pid = self._service_pid(service.id)
        if not pid: messagebox.showinfo('Switchyard', f'{service.name} is not currently running under Switchyard.'); return
        self._launch_or_offer('pulse', handoff_args('pulse', pid=pid))

    def _offer_crash_recovery(self):
        """Offer recovery once and explicitly acknowledge terminal user choices.

        Cancel deliberately keeps pending recovery armed so a subsequent crash cannot
        erase unresolved orphan-process information. Choosing to forget or restore
        acknowledges the old marker before normal operation continues.
        """
        marker = self._previous_recovery
        if not marker or not marker.get('active_session_id'):
            return
        session = next((s for s in self.state.sessions if s.id == marker.get('active_session_id')), None)
        rows = recovery_processes(marker); alive = [row for row in rows if row.alive]
        label = marker.get('active_session_name') or 'previous session'
        if not session:
            messagebox.showwarning('Switchyard recovery', f'Switchyard detected an unclean previous run for {label}, but that session no longer exists. The recovery marker will be forgotten.')
            acknowledge_recovery_journal(); self._previous_recovery = None
            return
        if alive:
            choice = messagebox.askyesnocancel('Switchyard recovery', f'The previous run ended while “{label}” was active.\n\n{len(alive)} recorded process(es) are still alive.\n\nYes — stop those orphan processes and restart the session\nNo — leave them alone and forget recovery\nCancel — leave them alone and inspect the workspace')
            if choice is True:
                failed = [row.pid for row in alive if not terminate_pid_tree(row.pid)]
                if failed:
                    messagebox.showerror('Switchyard recovery', 'Could not stop PID(s): ' + ', '.join(map(str, failed))); return
                acknowledge_recovery_journal(); self._previous_recovery = None
                self._select_and_start_recovery_session(session)
            elif choice is False:
                acknowledge_recovery_journal(); self._previous_recovery = None
            return
        restore = messagebox.askyesno('Switchyard recovery', f'The previous run ended while “{label}” was active, but no recorded process is still running.\n\nRestore that session now?')
        acknowledge_recovery_journal(); self._previous_recovery = None
        if restore:
            self._select_and_start_recovery_session(session)

    def refresh_projects(self, select=None):
        super().refresh_projects(select)
        if hasattr(self, 'tool_status'): self.refresh_ecosystem()

    def refresh_topology(self):
        super().refresh_topology()
        if hasattr(self, 'tool_status'): self.refresh_ecosystem()


if __name__ == '__main__':
    SwitchyardPhase6App().mainloop()
