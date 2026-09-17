# Switchyard

> A local-first developer workspace control plane: understand projects, orchestrate services, check readiness, and keep a development environment healthy from one desktop app.

![Switchyard interface preview](docs/interface-preview.svg)

Switchyard is the flagship Purysho desktop tool. It sits above individual repositories and gives you one place to understand projects, remember how they run, coordinate related services, and inspect what is happening while a workspace is alive.

## What it does now

### Workspace intelligence

Add any local project and Switchyard can surface:

- file and repository size
- Git branch, dirty state, upstream, ahead/behind counts, origin, and latest commit
- detected stacks such as Node.js, React, Next.js, Tauri, Python, Rust, Go, .NET, Java, and Docker
- common runnable tasks from project metadata
- project health checks and likely development ports
- notes, tags, pinning, and recent-project ordering

Detection is advisory. Switchyard does not silently execute discovered commands.

### Run configurations

Save project commands and run them from one place with:

- custom working directories
- live combined logs
- stop and restart controls
- persisted run history
- bounded log memory for long-running processes

A run configuration can be promoted into a service when it becomes part of a larger workspace.

### Services and dependency graphs

A service is a command with operational meaning. Each service has:

- a project
- a command and optional working directory
- dependencies on other services
- a readiness rule
- a startup timeout
- a failure policy

Switchyard validates dependency graphs, rejects missing dependencies and cycles, expands transitive requirements, and calculates deterministic startup order.

Supported readiness gates now include:

- **process** — continue once the process survives startup
- **port** — continue when a TCP port begins listening
- **HTTP** — continue when a local HTTP health/readiness URL returns successfully
- **delay** — continue after a deliberate startup delay

### Workspace sessions

A session is a named service topology such as:

```text
DATABASE
   ↓
API
   ↓
WEB
```

Starting a session causes Switchyard to:

1. run a preflight check
2. expand required dependencies
3. launch independent branches concurrently when safe
4. wait for readiness before advancing dependents
5. expose service state and combined output
6. record a persistent operational timeline
7. stop the topology in reverse dependency order

Unexpected failures can cascade to dependent services, or a service can be configured to continue without taking its dependents down.

### Environment profiles without stored secrets

The Runtime tab adds reusable profiles such as `local`, `test`, or `staging-like`.

A profile can contain normal non-secret variables, while secret keys can be marked **inherited**. Inherited values are read from the operating-system environment only when a process starts. Their values are never written into Switchyard's runtime file.

Profiles can be assigned to an entire session or overridden for an individual service.

### Resilient runtime

Services can use explicit restart policies:

- `never`
- `on_failure`
- `always`

Restarts are bounded by a maximum attempt count and exponential backoff ceiling. A new user-initiated session start receives a fresh restart budget, while stale restart workers from an earlier stopped run are invalidated. Switchyard records restart scheduling, restart success/failure, cascade stops, readiness failures, and degraded-session state in the session timeline.

### Preflight

Before a session starts, Switchyard can detect blocking or suspicious conditions including:

- invalid dependency graphs
- missing project folders
- missing inherited environment variables
- invalid readiness configuration
- duplicate claimed readiness ports
- ports already listening before startup
- commands that cannot be resolved on PATH

A readiness port that is already listening is a blocking V1 condition because an unrelated process could otherwise create a false READY result. Other blocking failures prevent startup; non-blocking command-resolution warnings remain explicit for review.

## Why Switchyard exists

Modern development frequently means remembering which repository, terminal command, port, environment, dependency, and startup order belongs to which project. Generic terminals know commands. Task managers know processes. IDEs know the current repository.

Switchyard's job is to know the **workspace**.

It is intentionally local-first:

- no account
- no cloud workspace
- no telemetry dependency
- no hosted orchestration service
- project files are never uploaded by Switchyard
- inherited secret values are not persisted by Switchyard

## First run

Switchyard does not require setup, sign-in, a server, or a pre-existing state file. Launch it, add a local project, then optionally save run configurations and promote commands into services/workspace sessions. State is created locally under `~/.switchyard` only when there is something to persist.

The V1 automated smoke test exercises an empty first run, project persistence, preflight, service startup/readiness, clean shutdown, and reload without touching the caller's real Switchyard profile.

## Running from source

Requires Python 3.10+ with Tk available. CI currently exercises Python 3.10 and 3.12 on both Ubuntu and Windows.

```bash
python switchyard_desktop.pyw
```

Tests:

```bash
python -m unittest discover -s tests -v
python tools/v1_smoke.py
```

## Windows build

```powershell
./build-windows.ps1
```

The repository CI tests supported Python versions on Ubuntu and Windows, performs a packaged Windows build, and launches the packaged executable in `--smoke-test` mode. Tagged release workflows repeat the V1 smoke gates before publishing the executable and checksum.

## State

The project/workspace model is stored at:

```text
~/.switchyard/state.json
```

Runtime profiles and restart policies are stored separately at:

```text
~/.switchyard/runtime.json
```

The workspace state format is versioned and continues to load older V1/V2 files. Current files are written atomically with rotating validated backups; corrupt or unsupported future-version files are preserved rather than silently overwritten. Environment profiles deliberately store inherited **key names**, not inherited secret values.

## Safety model

Switchyard runs commands you explicitly save, import, promote, or attach to services. Detected tasks remain suggestions until you choose to use them. Readiness checks only inspect local process state, TCP connectivity, configured HTTP endpoints, and elapsed startup time; Switchyard does not expose ports or configure networking.

See [SECURITY.md](SECURITY.md) for security reporting and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the internal model.

## V1 release hardening

The V1 release candidate is gated by destructive-state recovery, process-tree shutdown, bounded restart behavior, occupied-port fail-closed checks, concurrent-write safety, first-run smoke tests, full-module compilation, repeated cross-platform soak runs, and packaged executable verification after artifact re-download.

See [docs/V1_RELEASE_CHECKLIST.md](docs/V1_RELEASE_CHECKLIST.md) for the final automated and manual release gates. Longer-term work remains tracked in [docs/ROADMAP.md](docs/ROADMAP.md).

## License

MIT.
