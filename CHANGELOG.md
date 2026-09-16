# Changelog

## Unreleased

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
