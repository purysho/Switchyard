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
    ManagedProcess, Project, RunConfig, RunRecord,
    detect_project, load_state, new_project, project_health, project_snapshot,
    save_state, scan_local_ports, suggested_run_configs,
)

BG = '#090b0f'; PANEL = '#11161d'; PANEL2 = '#171e27'; TEXT = '#f2efe7'; MUTED = '#8f99a6'
GOLD = '#d9a84e'; CYAN = '#5dbde7'; GREEN = '#7edb9b'


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


class SwitchyardApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Switchyard — Local Developer Command Center')
        self.geometry('1480x900'); self.minsize(1120, 720); self.configure(bg=BG)
        self.state = load_state(); self.managed: dict[str, ManagedProcess] = {}; self.run_records: dict[str, RunRecord] = {}; self.detected = {}
        self._style(); self._build(); self.refresh_projects(self.state.selected_project); self.after(1000, self.tick)

    def _style(self):
        s = ttk.Style(self); s.theme_use('clam')
        s.configure('.', background=BG, foreground=TEXT, fieldbackground=PANEL)
        s.configure('TButton', background='#1d2630', foreground=TEXT, padding=8, borderwidth=0); s.map('TButton', background=[('active', '#293745')])
        s.configure('Accent.TButton', background='#6f5624', foreground='#fff7dc', padding=9); s.map('Accent.TButton', background=[('active', '#8b6b2c')])
        s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=29, borderwidth=0); s.map('Treeview', background=[('selected', '#26384a')])
        s.configure('Treeview.Heading', background=PANEL2, foreground=TEXT, relief='flat')
        s.configure('TNotebook', background=BG, borderwidth=0); s.configure('TNotebook.Tab', background=PANEL, foreground=MUTED, padding=(14, 8)); s.map('TNotebook.Tab', background=[('selected', PANEL2)], foreground=[('selected', TEXT)])

    def _build(self):
        top = tk.Frame(self, bg=BG); top.pack(fill='x', padx=18, pady=(14, 8))
        tk.Label(top, text='SWITCHYARD', bg=BG, fg=TEXT, font=('Segoe UI Semibold', 26)).pack(side='left')
        tk.Label(top, text='  workspace intelligence + local operations', bg=BG, fg=MUTED).pack(side='left', pady=(10, 0))
        ttk.Button(top, text='+ Add project', style='Accent.TButton', command=self.add_project).pack(side='right')

        main = tk.PanedWindow(self, orient='horizontal', bg='#202733', sashwidth=1); main.pack(fill='both', expand=True, padx=18, pady=(0, 18))
        self.sidebar = tk.Frame(main, bg=PANEL, width=285); self.content = tk.Frame(main, bg=BG); main.add(self.sidebar, minsize=250); main.add(self.content, minsize=760)
        side_head = tk.Frame(self.sidebar, bg=PANEL); side_head.pack(fill='x', padx=14, pady=(14, 8))
        tk.Label(side_head, text='PROJECTS', bg=PANEL, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(side='left')
        self.project_count = tk.Label(side_head, text='0', bg=PANEL, fg=MUTED, font=('Consolas', 9)); self.project_count.pack(side='right')
        self.project_list = tk.Listbox(self.sidebar, bg=PANEL, fg=TEXT, selectbackground='#273646', highlightthickness=0, borderwidth=0, font=('Segoe UI', 11), activestyle='none')
        self.project_list.pack(fill='both', expand=True, padx=8, pady=(0, 8)); self.project_list.bind('<<ListboxSelect>>', self.on_project)
        side_actions = tk.Frame(self.sidebar, bg=PANEL); side_actions.pack(fill='x', padx=10, pady=10)
        ttk.Button(side_actions, text='Pin / unpin', command=self.toggle_pin).pack(fill='x', pady=(0, 6)); ttk.Button(side_actions, text='Tags', command=self.edit_tags).pack(fill='x', pady=(0, 6)); ttk.Button(side_actions, text='Remove', command=self.remove_project).pack(fill='x')

        self.header = tk.Frame(self.content, bg=BG); self.header.pack(fill='x', padx=18, pady=(8, 12)); title_row = tk.Frame(self.header, bg=BG); title_row.pack(fill='x')
        self.project_title = tk.Label(title_row, text='Select a project', bg=BG, fg=TEXT, font=('Segoe UI Semibold', 24)); self.project_title.pack(side='left')
        ttk.Button(title_row, text='Open folder', command=self.open_current_folder).pack(side='right')
        self.project_meta = tk.Label(self.header, text='', bg=BG, fg=MUTED, font=('Consolas', 10), justify='left'); self.project_meta.pack(anchor='w', pady=(4, 0))
        self.project_tags = tk.Label(self.header, text='', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)); self.project_tags.pack(anchor='w', pady=(5, 0))

        self.nb = ttk.Notebook(self.content); self.nb.pack(fill='both', expand=True, padx=18, pady=(0, 12))
        self.overview = tk.Frame(self.nb, bg=BG); self.intelligence = tk.Frame(self.nb, bg=BG); self.runs = tk.Frame(self.nb, bg=BG); self.history = tk.Frame(self.nb, bg=BG); self.live = tk.Frame(self.nb, bg=BG)
        self.nb.add(self.overview, text='Overview'); self.nb.add(self.intelligence, text='Intelligence'); self.nb.add(self.runs, text='Run configurations'); self.nb.add(self.history, text='History'); self.nb.add(self.live, text='Live processes')
        self._overview(); self._intelligence(); self._runs(); self._history(); self._live()

    def _overview(self):
        self.cards = tk.Frame(self.overview, bg=BG); self.cards.pack(fill='x', pady=12); self.card_labels = []
        for label in ['FILES', 'SIZE', 'GIT', 'BRANCH', 'STACK', 'PORTS']:
            frame = tk.Frame(self.cards, bg=PANEL, highlightbackground='#222b35', highlightthickness=1); frame.pack(side='left', fill='both', expand=True, padx=4)
            tk.Label(frame, text=label, bg=PANEL, fg=MUTED, font=('Segoe UI Semibold', 8)).pack(anchor='w', padx=12, pady=(10, 2))
            value = tk.Label(frame, text='—', bg=PANEL, fg=TEXT, font=('Segoe UI Semibold', 15), wraplength=160, justify='left'); value.pack(anchor='w', padx=12, pady=(0, 12)); self.card_labels.append(value)
        self.git_detail = tk.Label(self.overview, text='', bg=BG, fg=MUTED, font=('Consolas', 10), justify='left'); self.git_detail.pack(anchor='w', padx=4, pady=(10, 2))
        tk.Label(self.overview, text='NOTES', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(anchor='w', pady=(18, 4))
        self.notes = tk.Text(self.overview, bg=PANEL, fg=TEXT, insertbackground=TEXT, height=10, relief='flat', wrap='word'); self.notes.pack(fill='both', expand=True); self.notes.bind('<FocusOut>', lambda _e: self.save_notes())

    def _intelligence(self):
        top = tk.Frame(self.intelligence, bg=BG); top.pack(fill='x', pady=(10, 6)); ttk.Button(top, text='Refresh intelligence', command=self.refresh_intelligence).pack(side='left'); ttk.Button(top, text='Import detected tasks', style='Accent.TButton', command=self.import_detected_tasks).pack(side='left', padx=8)
        self.stack_summary = tk.Label(self.intelligence, text='No project selected', bg=PANEL, fg=TEXT, anchor='w', justify='left', padx=14, pady=12, font=('Segoe UI Semibold', 11)); self.stack_summary.pack(fill='x', pady=(4, 12))
        split = tk.PanedWindow(self.intelligence, orient='horizontal', bg='#202733', sashwidth=1); split.pack(fill='both', expand=True); left = tk.Frame(split, bg=BG); right = tk.Frame(split, bg=BG); split.add(left, minsize=420); split.add(right, minsize=420)
        tk.Label(left, text='DETECTED TASKS', bg=BG, fg=CYAN, font=('Segoe UI Semibold', 9)).pack(anchor='w', pady=(0, 4))
        self.task_tree = ttk.Treeview(left, columns=('name', 'command', 'source'), show='headings')
        for col, title, width in [('name', 'NAME', 140), ('command', 'COMMAND', 270), ('source', 'SOURCE', 130)]: self.task_tree.heading(col, text=title); self.task_tree.column(col, width=width)
        self.task_tree.pack(fill='both', expand=True, padx=(0, 6))
        tk.Label(right, text='HEALTH', bg=BG, fg=GREEN, font=('Segoe UI Semibold', 9)).pack(anchor='w', pady=(0, 4))
        self.health_tree = ttk.Treeview(right, columns=('state', 'check', 'detail'), show='headings')
        for col, title, width in [('state', 'STATE', 80), ('check', 'CHECK', 190), ('detail', 'DETAIL', 220)]: self.health_tree.heading(col, text=title); self.health_tree.column(col, width=width)
        self.health_tree.pack(fill='both', expand=True, padx=(6, 0))

    def _runs(self):
        bar = tk.Frame(self.runs, bg=BG); bar.pack(fill='x', pady=10)
        ttk.Button(bar, text='+ Add run config', command=self.add_run).pack(side='left'); ttk.Button(bar, text='Edit', command=self.edit_run).pack(side='left', padx=(8, 0)); ttk.Button(bar, text='Delete', command=self.delete_run).pack(side='left', padx=8)
        ttk.Button(bar, text='Run', style='Accent.TButton', command=self.run_selected).pack(side='left', padx=(12, 8)); ttk.Button(bar, text='Restart', command=self.restart_selected).pack(side='left'); ttk.Button(bar, text='Stop', command=self.stop_selected).pack(side='left', padx=8)
        self.run_tree = ttk.Treeview(self.runs, columns=('name', 'command', 'cwd', 'state'), show='headings')
        for col, title, width in [('name', 'NAME', 180), ('command', 'COMMAND', 520), ('cwd', 'CWD', 220), ('state', 'STATE', 110)]: self.run_tree.heading(col, text=title); self.run_tree.column(col, width=width)
        self.run_tree.pack(fill='both', expand=True)

    def _history(self):
        bar = tk.Frame(self.history, bg=BG); bar.pack(fill='x', pady=10); tk.Label(bar, text='RECENT RUNS', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(side='left'); ttk.Button(bar, text='Clear history', command=self.clear_history).pack(side='right')
        self.history_tree = ttk.Treeview(self.history, columns=('time', 'project', 'config', 'result', 'duration', 'pid'), show='headings')
        for col, title, width in [('time', 'STARTED', 170), ('project', 'PROJECT', 170), ('config', 'CONFIG', 180), ('result', 'RESULT', 110), ('duration', 'DURATION', 100), ('pid', 'PID', 90)]: self.history_tree.heading(col, text=title); self.history_tree.column(col, width=width)
        self.history_tree.pack(fill='both', expand=True)

    def _live(self):
        self.live_tree = ttk.Treeview(self.live, columns=('project', 'config', 'pid', 'uptime', 'state'), show='headings')
        for col, title, width in [('project', 'PROJECT', 180), ('config', 'CONFIG', 180), ('pid', 'PID', 90), ('uptime', 'UPTIME', 120), ('state', 'STATE', 120)]: self.live_tree.heading(col, text=title); self.live_tree.column(col, width=width)
        self.live_tree.pack(fill='x', pady=(10, 8)); tk.Label(self.live, text='COMBINED OUTPUT', bg=BG, fg=GOLD, font=('Segoe UI Semibold', 9)).pack(anchor='w')
        self.log = tk.Text(self.live, bg='#07090c', fg='#b7c5d3', insertbackground=TEXT, relief='flat', font=('Consolas', 10)); self.log.pack(fill='both', expand=True, pady=(4, 0))

    def current(self) -> Project | None:
        selection = self.project_list.curselection()
        if not selection: return None
        project_id = self.project_list.get(selection[0]).split('::', 1)[0]
        return next((p for p in self.state.projects if p.id == project_id), None)

    def _ordered_projects(self): return sorted(self.state.projects, key=lambda p: (not p.pinned, -(p.last_opened or 0), p.name.lower()))

    def refresh_projects(self, select=None):
        self.project_list.delete(0, 'end'); ordered = self._ordered_projects(); target = select or self.state.selected_project; target_index = None
        for i, p in enumerate(ordered):
            marker = '★ ' if p.pinned else ''; tags = f"  [{', '.join(p.tags)}]" if p.tags else ''; self.project_list.insert('end', f'{p.id}::{marker}{p.name}{tags}')
            if p.id == target: target_index = i
        self.project_count.config(text=str(len(ordered)))
        if ordered:
            idx = target_index if target_index is not None else 0; self.project_list.selection_set(idx); self.project_list.see(idx); self.project_list.event_generate('<<ListboxSelect>>')

    def add_project(self):
        path = filedialog.askdirectory()
        if not path: return
        resolved = str(Path(path).resolve()); existing = next((p for p in self.state.projects if str(Path(p.path).resolve()) == resolved), None)
        if existing: self.refresh_projects(existing.id); return
        proj = new_project(path); self.state.projects.append(proj); self.state.selected_project = proj.id; save_state(self.state); self.refresh_projects(proj.id)

    def remove_project(self):
        p = self.current()
        if not p: return
        if any(mp.running and mp.project.id == p.id for mp in self.managed.values()): messagebox.showwarning('Switchyard', 'Stop this project\'s running processes before removing it.'); return
        if messagebox.askyesno('Switchyard', f'Remove {p.name} from Switchyard? Files will not be touched.'):
            self.state.projects = [x for x in self.state.projects if x.id != p.id]
            if self.state.selected_project == p.id: self.state.selected_project = None
            save_state(self.state); self.refresh_projects()

    def toggle_pin(self):
        p = self.current()
        if p: p.pinned = not p.pinned; save_state(self.state); self.refresh_projects(p.id)

    def edit_tags(self):
        p = self.current()
        if not p: return
        value = simpledialog.askstring('Project tags', 'Comma-separated tags:', initialvalue=', '.join(p.tags))
        if value is None: return
        p.tags = sorted({x.strip() for x in value.split(',') if x.strip()}); save_state(self.state); self.refresh_projects(p.id)

    def open_current_folder(self):
        p = self.current()
        if p: open_folder(p.path)

    def on_project(self, _event=None):
        p = self.current()
        if not p: return
        p.last_opened = time.time(); self.state.selected_project = p.id; save_state(self.state)
        self.project_title.config(text=('★ ' if p.pinned else '') + p.name); self.project_meta.config(text=p.path); self.project_tags.config(text=' · '.join(p.tags).upper() if p.tags else '')
        self.notes.delete('1.0', 'end'); self.notes.insert('1.0', p.notes); self.refresh_snapshot(p); self.refresh_runs(p); self.refresh_intelligence(); self.refresh_history()

    def refresh_snapshot(self, p):
        def go():
            snap = project_snapshot(p); detected = detect_project(p.path); likely_ports = detected['ports'] or [3000, 4173, 5173, 8000, 8080, 1420, 5000]; ports = scan_local_ports(likely_ports); self.after(0, lambda: self.show_snapshot(p.id, snap, detected, ports))
        threading.Thread(target=go, daemon=True).start()

    def show_snapshot(self, project_id, snap, detected, ports):
        p = self.current()
        if not p or p.id != project_id: return
        git_state = '—'
        if snap['git']: git_state = f"{snap['changed']} change" + ('s' if snap['changed'] != 1 else '') if snap['dirty'] else 'CLEAN'
        stack = ' · '.join(detected['stacks'][:3]) or 'Unknown'; vals = [f"{snap['files']:,}", fmt_bytes(snap['bytes']), git_state, snap['branch'] or '—', stack, ', '.join(map(str, ports)) or 'none']
        for label, value in zip(self.card_labels, vals): label.config(text=value)
        detail = []
        if snap['upstream']: detail.append(f"upstream {snap['upstream']} · ↑{snap['ahead']} ↓{snap['behind']}")
        if snap['last_commit']: detail.append(f"last {snap['last_commit']}")
        if snap['remote']: detail.append(f"origin {snap['remote']}")
        self.git_detail.config(text='\n'.join(detail))

    def save_notes(self):
        p = self.current()
        if p: p.notes = self.notes.get('1.0', 'end').rstrip(); save_state(self.state)

    def refresh_intelligence(self):
        p = self.current()
        if not p: return
        project_id = p.id; self.stack_summary.config(text='Inspecting project metadata…'); self.task_tree.delete(*self.task_tree.get_children()); self.health_tree.delete(*self.health_tree.get_children())
        def go():
            detected = detect_project(p.path); health = project_health(p); self.after(0, lambda: self.show_intelligence(project_id, detected, health))
        threading.Thread(target=go, daemon=True).start()

    def show_intelligence(self, project_id, detected, health):
        p = self.current()
        if not p or p.id != project_id: return
        self.detected[project_id] = detected; stack_text = ' · '.join(detected['stacks']) or 'No known stack detected'; evidence = ', '.join(detected['evidence']) or 'no recognized manifests'; self.stack_summary.config(text=f'{stack_text}\nEvidence: {evidence}')
        self.task_tree.delete(*self.task_tree.get_children())
        for i, task in enumerate(detected['tasks']): self.task_tree.insert('', 'end', iid=f'task-{i}', values=(task['name'], task['command'], task['source']))
        self.health_tree.delete(*self.health_tree.get_children())
        for i, check in enumerate(health):
            state = 'PASS' if check['ok'] else ('INFO' if check['kind'] == 'port' else 'CHECK'); self.health_tree.insert('', 'end', iid=f'health-{i}', values=(state, check['name'], check['detail']))

    def import_detected_tasks(self):
        p = self.current()
        if not p: return
        suggestions = suggested_run_configs(p)
        if not suggestions: messagebox.showinfo('Switchyard', 'No new detected tasks to import.'); return
        summary = '\n'.join(f'• {c.name}: {c.command}' for c in suggestions)
        if not messagebox.askyesno('Import detected tasks', f'Add these run configurations?\n\n{summary}'): return
        p.run_configs.extend(suggestions); save_state(self.state); self.refresh_runs(p); self.refresh_intelligence()

    def add_run(self):
        p = self.current()
        if not p: return
        name = simpledialog.askstring('Run configuration', 'Name:')
        if not name: return
        command = simpledialog.askstring('Run configuration', 'Command:')
        if not command: return
        cwd = simpledialog.askstring('Run configuration', 'Working directory (blank = project root):', initialvalue=''); p.run_configs.append(RunConfig(uuid.uuid4().hex, name, command, cwd or None)); save_state(self.state); self.refresh_runs(p); self.refresh_intelligence()

    def _selected_config(self):
        p = self.current(); sel = self.run_tree.selection()
        if not p or not sel: return p, None
        return p, next((x for x in p.run_configs if x.id == sel[0]), None)

    def edit_run(self):
        p, config = self._selected_config()
        if not p or not config: return
        if config.id in self.managed and self.managed[config.id].running: messagebox.showwarning('Switchyard', 'Stop this configuration before editing it.'); return
        name = simpledialog.askstring('Run configuration', 'Name:', initialvalue=config.name)
        if not name: return
        command = simpledialog.askstring('Run configuration', 'Command:', initialvalue=config.command)
        if not command: return
        cwd = simpledialog.askstring('Run configuration', 'Working directory (blank = project root):', initialvalue=config.cwd or ''); config.name, config.command, config.cwd = name, command, cwd or None; save_state(self.state); self.refresh_runs(p); self.refresh_intelligence()

    def delete_run(self):
        p, config = self._selected_config()
        if not p or not config: return
        if config.id in self.managed and self.managed[config.id].running: messagebox.showwarning('Switchyard', 'Stop this configuration before deleting it.'); return
        if messagebox.askyesno('Switchyard', f'Delete run configuration “{config.name}”?'):
            p.run_configs = [c for c in p.run_configs if c.id != config.id]; self.managed.pop(config.id, None); save_state(self.state); self.refresh_runs(p); self.refresh_intelligence()

    def refresh_runs(self, p):
        selected = self.run_tree.selection(); self.run_tree.delete(*self.run_tree.get_children())
        for config in p.run_configs:
            mp = self.managed.get(config.id); state = 'RUNNING' if mp and mp.running else (f'EXIT {mp.returncode}' if mp and mp.returncode is not None else 'IDLE'); self.run_tree.insert('', 'end', iid=config.id, values=(config.name, config.command, config.cwd or '.', state))
        if selected and self.run_tree.exists(selected[0]): self.run_tree.selection_set(selected[0])

    def run_selected(self):
        p, config = self._selected_config()
        if not p or not config: return
        existing = self.managed.get(config.id)
        if existing and existing.running: messagebox.showinfo('Switchyard', f'{config.name} is already running.'); return
        mp = ManagedProcess(config, p); self.managed[config.id] = mp; record = RunRecord(uuid.uuid4().hex, p.id, p.name, config.id, config.name, config.command, time.time()); self.run_records[config.id] = record; self.state.run_history.append(record); save_state(self.state)
        try:
            pid = mp.start(lambda line: self.after(0, lambda text=line: self.append_log(p.name, config.name, text)), lambda rc: self.after(0, lambda: self.process_exit(p, config, rc)))
        except Exception as exc:
            record.ended_at = time.time(); record.returncode = -1; save_state(self.state); messagebox.showerror('Switchyard', str(exc)); self.refresh_history(); return
        record.pid = pid; save_state(self.state); self.append_log(p.name, config.name, f'▶ started pid {pid}'); self.refresh_runs(p); self.refresh_live(); self.refresh_history()

    def stop_selected(self):
        _p, config = self._selected_config()
        if config and config.id in self.managed: self.managed[config.id].stop(); self.refresh_live()

    def restart_selected(self):
        p, config = self._selected_config()
        if not p or not config: return
        existing = self.managed.get(config.id)
        if existing and existing.running: existing.stop(); self.after(250, self.run_selected)
        else: self.run_selected()

    def append_log(self, project, config, line):
        self.log.insert('end', f'[{project}/{config}] {line}\n')
        try:
            lines = int(self.log.index('end-1c').split('.')[0])
            if lines > 6000: self.log.delete('1.0', '1000.0')
        except Exception: pass
        self.log.see('end')

    def process_exit(self, p, config, rc):
        self.append_log(p.name, config.name, f'■ exited {rc}'); record = self.run_records.pop(config.id, None)
        if record: record.ended_at = time.time(); record.returncode = rc; save_state(self.state)
        self.refresh_runs(p); self.refresh_live(); self.refresh_history()
        if config.auto_restart and rc != 0: self.after(1000, lambda: self._run_config_direct(p, config))

    def _run_config_direct(self, p, config):
        self.refresh_projects(p.id)
        if self.run_tree.exists(config.id): self.run_tree.selection_set(config.id); self.nb.select(self.runs); self.run_selected()

    def refresh_live(self):
        self.live_tree.delete(*self.live_tree.get_children()); now = time.time()
        for config_id, mp in self.managed.items():
            pid = mp.process.pid if mp.process else ''; up = fmt_duration(now - mp.started_at) if mp.started_at and mp.running else fmt_duration((mp.ended_at or now) - mp.started_at) if mp.started_at else '—'; state = 'RUNNING' if mp.running else f'EXIT {mp.returncode}'; self.live_tree.insert('', 'end', iid=config_id, values=(mp.project.name, mp.config.name, pid, up, state))

    def refresh_history(self):
        self.history_tree.delete(*self.history_tree.get_children())
        for record in reversed(self.state.run_history[-250:]):
            started = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(record.started_at)); result = 'RUNNING' if record.ended_at is None else ('PASS' if record.returncode == 0 else f'EXIT {record.returncode}'); self.history_tree.insert('', 'end', iid=record.id, values=(started, record.project_name, record.config_name, result, fmt_duration(record.duration), record.pid or ''))

    def clear_history(self):
        if any(mp.running for mp in self.managed.values()): messagebox.showwarning('Switchyard', 'Stop running processes before clearing run history.'); return
        if messagebox.askyesno('Switchyard', 'Clear saved run history?'): self.state.run_history.clear(); save_state(self.state); self.refresh_history()

    def tick(self):
        self.refresh_live(); p = self.current()
        if p: self.refresh_runs(p)
        self.after(1000, self.tick)

    def destroy(self):
        for mp in self.managed.values():
            if mp.running: mp.stop()
        super().destroy()


if __name__ == '__main__': SwitchyardApp().mainloop()
