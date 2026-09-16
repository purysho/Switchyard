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

## Phase 4 — Environments + resilient runtime

Next priorities:

- environment profiles (`local`, `test`, `staging-like`) without storing secrets in plaintext
- per-service environment overrides
- HTTP readiness probes and richer health checks
- restart policies with bounded backoff
- startup concurrency for independent branches of a graph
- orphan/crash detection when Switchyard restarts
- session snapshots and one-click restore
- clearer failure diagnosis and event filtering

## Phase 5 — Workspace topology

- interactive service graph
- port ownership and conflict detection
- repository/service relationship map
- live dependency state overlays
- service-specific log streams and search
- session templates export/import

## Phase 6 — Deep integration

Potential integrations should remain optional and local:

- Docker / Compose observation without taking ownership away from Docker
- Git worktree awareness
- terminal/editor handoff
- BLACKBOX repository intelligence handoff
- Relay endpoint handoff
- Pulse process/network handoff

The product principle remains: **Switchyard coordinates the workspace; specialized Purysho tools can inspect individual layers more deeply.**
