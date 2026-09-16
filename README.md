<div align="center">
  <img src="assets/icon.svg" width="132" alt="Switchyard icon">
  <h1>Switchyard</h1>
  <p><strong>A local developer command center that understands projects, runs their workflows, and keeps operational context in one place.</strong></p>
</div>

![Switchyard desktop interface preview](docs/interface-preview.svg)

## Why Switchyard exists

Developer work is spread across terminals, task runners, Git commands, notes, localhost ports, process monitors, and project folders. Switchyard is a local-first workspace that brings those operational pieces together without requiring an account or hosted backend.

## Phase 2 — Workspace Intelligence

Switchyard now goes beyond a project launcher:

- **Project detection** — recognizes Node.js, React, Next.js, Tauri, Python, Rust, Go, .NET, Java, Docker and Docker Compose from local project evidence.
- **Detected tasks** — reads common project manifests and proposes useful run configurations without silently modifying the workspace.
- **Git intelligence** — branch, dirty-file count, upstream, ahead/behind, latest commit and origin remote.
- **Health view** — checks the project folder, Git working tree, run-command availability, and likely development ports.
- **Persistent run history** — records command, PID, timestamps, result and duration for recent runs.
- **Richer project metadata** — pinned projects, tags and last-opened timestamps are part of the versioned workspace state.
- **Managed processes** — start and stop saved project commands with combined live output.

## Current product model

Switchyard is intentionally **local-first and explicit**. Detection can suggest actions, but it does not automatically run project scripts or modify repositories. Commands only execute when the user chooses to run them.

## Run from source

Requirements: Python 3.10+ with Tk support. Git is optional but enables repository intelligence.

```powershell
pyw switchyard_desktop.pyw
```

The runtime uses Python's standard library.

## Test

```powershell
python -m unittest discover -s tests -v
```

## Build for Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

## Roadmap

Phase 2 establishes workspace intelligence. The next major layers are:

1. **Service graph** — model projects as cooperating services rather than isolated commands.
2. **Workspace sessions** — start/stop named groups of services together with dependency ordering.
3. **Environment profiles** — explicit local/dev/test variable sets with secret-safe handling.
4. **Operational timeline** — correlate runs, exits, Git changes and ports over time.
5. **Project adapters** — deeper framework-specific insight without turning Switchyard into an IDE.

See [docs/ROADMAP.md](docs/ROADMAP.md) for the product plan.

## Privacy and safety

State is stored under `~/.switchyard/`. Switchyard does not upload projects, source code, notes or command output. Detection only reads local metadata. A saved run configuration can execute arbitrary commands, so imported/shared state should be reviewed before running it.

## License

MIT
