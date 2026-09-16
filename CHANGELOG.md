# Changelog

## Unreleased

### V1 hardening + release QA

- Added destructive-state recovery coverage for corrupt current files, rotating backup fallback, unsupported future schemas, interrupted atomic replacement, and evidence preservation.
- Added strict nested-schema validation so malformed string values cannot be silently split into character lists.
- Added per-path serialized atomic persistence with unique temporary files, fsync, and crash-safe log exports.
- Added lifecycle abuse tests for rapid stop/start/restart, duplicate starts, missing projects/executables, concurrent service failures, occupied readiness ports, and real spawned process trees.
- Made preoccupied readiness ports blocking in V1 so unrelated listeners cannot produce a false READY result.
- Added generation-scoped restart workers so stale backoff threads cannot relaunch processes after a stop/start cycle; restart budgets now reset on each user-initiated session start.
- Hardened crash recovery so unresolved orphan-process evidence survives repeated Switchyard crashes until the user explicitly resolves or forgets it.
- Added a headless first-run smoke test covering empty state, project persistence, preflight, startup/readiness, shutdown, and reload.
- Added packaged `Switchyard.exe --smoke-test` support and made CI/release workflows gate on both the headless first-run test and packaged executable launch.
- Expanded CI compilation checks to every `switchyard_*.py` module plus the desktop entrypoint.
- Added `docs/V1_RELEASE_CHECKLIST.md` for automated, destructive, first-run, packaging, and manual Windows release gates.

### Phase 5 — Visual Topology + Recovery

- Added a dedicated live topology canvas with deterministic dependency layout and runtime status overlays.
- Added visual port-conflict warnings and service inspection from topology nodes.
- Added focused per-service log streams with bounded memory, search, level filtering, follow-tail, clear, and export controls.
- Added crash-recovery journaling that records active sessions and child PIDs without persisting process handles.
- Added explicit recovery choices for orphaned processes after an unclean Switchyard exit.
- Added secret-free session snapshots and one-click restore into the current workspace.
- Added portable session template export/import with project mapping for different local paths or project names.
- Added safe Windows PID liveness checks that never signal or terminate the inspected process.
- Added Phase 5 tests for topology layering, port conflicts, log filtering, templates, snapshots, and recovery markers.

### Phase 4 — Environments + Resilient Runtime

- Added separate runtime settings storage for environment profiles and service runtime policy.
- Added environment profiles with stored non-secret variables and inherited OS environment keys.
- Inherited secret values are resolved only at launch and are never persisted by Switchyard.
- Added session-level environment assignment plus per-service profile overrides.
- Added HTTP readiness probes alongside process, TCP-port, and delay readiness gates.
- Added session preflight checks for graph errors, missing projects, unresolved commands, missing inherited variables, invalid readiness configuration, duplicate claimed ports, and already-open ports.
- Added parallel startup for independent services in the same dependency layer.
- Added explicit restart policies: never, on-failure, and always.
- Added bounded restart attempts with exponential backoff and a configurable backoff ceiling.
- Added restart, restart-ready, restart-failed, preflight-error, degraded-session, and cascade-stop timeline events.
- Added a Runtime desktop tab for profiles, service policies, session environment assignment, HTTP readiness, and preflight review.
- Split the stable Phase 3 desktop shell into a reusable base module so flagship runtime behavior can evolve independently.
- Added cross-platform runtime tests and retained Windows packaged-build checks.

### Phase 3 — Service Graph + Workspace Sessions

- Added version 3 workspace state with services, sessions, readiness rules, and session event history.
- Added cross-project service definitions with dependencies and explicit failure policies.
- Added deterministic dependency expansion and topological startup ordering.
- Added process, TCP-port, and delay readiness gates with timeouts.
- Added `SessionController` orchestration with dependency-aware startup and reverse-order shutdown.
- Added dependent-service cascade stops after unexpected failures.
- Added persistent session timeline events.
- Added Services and Sessions desktop tabs with graph validation, service editing, session editing, start/stop controls, topology inspection, and live state.
- Added promotion from run configuration to service.
- Expanded the Live Processes view to include session-managed services.
- Added Phase 3 tests for migration, graph ordering, cycle rejection, readiness, and full dependency startup.

### Phase 2 — Workspace Intelligence

- Added project stack detection, Git intelligence, health checks, task suggestions, persisted run history, tags, pinning, and richer run configuration controls.

## 0.1.0

- Initial local developer workspace command center.
