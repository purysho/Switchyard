# Switchyard flagship roadmap

Switchyard should become a dependable **local development workspace control plane**, not a generic shell wrapper.

## Phase 1 — Command center ✅

- project registry
- notes
- run configurations
- managed processes
- combined output
- local port visibility

## Phase 2 — Workspace intelligence ✅

- stack and task detection
- Git intelligence
- project health
- run history
- tags and pinning
- richer run configuration management

## Phase 3 — Service graph + workspace sessions ✅

- cross-project services
- dependency graph validation
- transitive dependency expansion
- deterministic startup order
- process / port / delay readiness gates
- named workspace sessions
- reverse-order shutdown
- persistent orchestration timeline
- dependent failure cascades
- topology and live-service UI

## Phase 4 — Environments + resilient runtime ✅

- environment profiles without persisting inherited secret values
- session-level profiles and per-service overrides
- HTTP readiness probes
- session preflight diagnostics
- duplicate readiness-port detection
- parallel startup for independent dependency branches
- `never`, `on_failure`, and `always` restart policies
- bounded exponential restart backoff
- resilient-runtime event history
- dedicated Runtime desktop controls

## Phase 5 — Visual topology + recovery

Next priorities:

- interactive service graph rather than text-only topology
- live dependency-state overlays
- port ownership and conflict attribution
- service-specific log streams, filtering, and search
- process identity snapshots for orphan/crash detection
- recovery notice after unclean Switchyard shutdown
- session snapshots and explicit one-click restore
- session templates export/import
- clearer event filtering and failure diagnosis

## Phase 6 — Deep integration

Potential integrations should remain optional and local:

- Docker / Compose observation without taking ownership away from Docker
- Git worktree awareness
- terminal/editor handoff
- BLACKBOX repository intelligence handoff
- Relay endpoint handoff
- Pulse process/network handoff

## Product rule

**Switchyard coordinates the workspace; specialized Purysho tools inspect individual layers more deeply.**

Integrations should therefore be handoffs and shared context, not attempts to rebuild BLACKBOX, Relay, Pulse, or the operating system inside Switchyard.
