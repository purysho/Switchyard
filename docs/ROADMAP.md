# Switchyard flagship roadmap

Switchyard should remain a dependable **local development workspace control plane**, not a generic shell wrapper.

## V1.0 — released ✅

The initial public release includes:

- project registry, notes, tags and pinning
- workspace intelligence and task/stack detection
- Git status and repository health
- run configurations and bounded live logs
- cross-project services
- dependency graph validation and transitive dependency expansion
- deterministic and parallel-safe service startup
- process / port / HTTP / delay readiness
- workspace sessions and reverse-order shutdown
- environment profiles without persisted inherited secret values
- preflight diagnostics and occupied-port fail-closed checks
- bounded restart policies and exponential backoff
- visual topology and live dependency state
- service-specific log views, filtering and search
- crash/orphan recovery
- session snapshots
- session template import/export
- optional local handoffs to BLACKBOX, Needle, Relay and Pulse
- dashboard and command palette
- Windows portable executable with checksum publication

## Post-v1.0 observation

The immediate priority is **observation, not feature expansion**.

See [../POST_V1_OBSERVATION.md](../POST_V1_OBSERVATION.md).

A v1.0.1 release should happen only for a reproducible bounded defect or release regression. New capabilities should wait for v1.1.

## V1.1 candidate areas

Only promote these after real use shows they are worth the added surface:

- richer port ownership/conflict attribution
- deeper Docker / Compose observation without taking ownership away from Docker
- Git worktree awareness
- improved first-run onboarding and workspace examples
- richer event filtering and diagnosis
- additional ecosystem context handoff where it reduces duplicate setup
- performance tuning for unusually large repositories if observation data shows a real bottleneck

## Product rule

**Switchyard coordinates the workspace; specialized Purysho tools inspect individual layers more deeply.**

Integrations should remain local handoffs and shared context, not attempts to rebuild BLACKBOX, Relay, Pulse, Needle, or the operating system inside Switchyard.
