# Switchyard Roadmap

Switchyard's flagship direction is **local development operations**, not code editing. The product should answer four questions quickly:

1. What is this project?
2. What does it need to run?
3. What is running now?
4. What changed when something went wrong?

## Phase 2 — Workspace Intelligence

- Project/framework detection.
- Git and repository context.
- Suggested tasks.
- Health checks.
- Persistent run history.

## Phase 3 — Service Graph

Treat a workspace as a graph of services rather than a list of shell commands.

Planned model:

- Service: command + cwd + environment + expected ports.
- Dependency: `web` waits for `api`; `api` waits for `db`.
- Readiness: port-open, process-running, or log-pattern checks.
- Session: named set of services with deterministic start/stop ordering.
- Failure policy: stop dependents, continue, or restart with bounded backoff.

The graph should remain explicit and inspectable; Switchyard should never infer destructive orchestration actions.

## Phase 4 — Operational Timeline

Create a local event stream for:

- process start/stop/restart,
- exit codes,
- readiness transitions,
- Git branch/dirty-state changes,
- port appearance/disappearance,
- user annotations.

This should enable post-mortem answers such as: *"the API stopped listening on 8000 18 seconds after the frontend build changed."*

## Phase 5 — Environment Profiles

- Local/dev/test profiles.
- Plain variables stored in workspace state.
- Secrets referenced from OS environment or external secret providers rather than copied into Switchyard state.
- Per-service overrides with a resolved-environment preview before launch.

## Phase 6 — Project Adapters

Deeper but optional adapters for ecosystems such as:

- Node / package scripts
- Tauri
- Python
- Cargo
- Docker Compose

Adapters should contribute metadata, task suggestions and readiness hints. They should not turn Switchyard into a package manager or IDE.

## Non-goals

- Cloud deployment platform.
- Hosted team collaboration product.
- Source-code editor.
- Automatic execution of detected scripts.
- Secret vault.

Switchyard should stay a fast, understandable local control plane.
