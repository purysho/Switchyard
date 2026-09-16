# Switchyard architecture

Switchyard deliberately separates **stored workspace intent**, **runtime policy**, and **live process state**.

## Workspace model

`~/.switchyard/state.json` contains versioned workspace intent:

- `Project` — a local repository/folder and its human context
- `RunConfig` — a reusable command attached to one project
- `Service` — an operational command that can depend on other services
- `WorkspaceSession` — a named set of services to orchestrate together
- `RunRecord` — history for direct run configurations
- `SessionEvent` — the operational timeline for session orchestration

No process handles or volatile runtime objects are serialized.

## Runtime policy

Phase 4 keeps resilience/environment policy in a separate file:

`~/.switchyard/runtime.json`

It contains:

- `EnvironmentProfile` — non-secret variable values plus names of variables to inherit from the operating-system environment
- `ServiceRuntimePolicy` — restart strategy, attempt limits, backoff, and optional service-level environment profile
- session → environment-profile assignment
- the most recently started session identifier

Inherited environment **values are not persisted**. Only their key names are stored. Values are resolved from the current process environment immediately before a managed service starts.

This is deliberate: Switchyard is not a secrets vault.

## Process model

`ManagedProcess` owns one local subprocess tree and its bounded output buffer.

Process groups are created so stop operations target the managed tree rather than only the intermediate shell:

- Windows uses a new process group plus `taskkill /T`
- POSIX uses a new session/process group and group signals

This also prevents child processes retaining temporary/test directories after the parent shell exits.

## Session orchestration

Phase 3 `SessionController` provides deterministic dependency-aware startup.

Phase 4 `ResilientSessionController` extends that behavior with:

1. session preflight
2. environment-profile resolution
3. transitive dependency expansion
4. startup by dependency layer
5. safe parallel startup for independent services in the same layer
6. process / port / HTTP / delay readiness
7. bounded restart policy
8. dependent cascade behavior after restart exhaustion
9. persistent runtime events
10. reverse-order shutdown

The controller remains UI-independent so orchestration behavior can be exercised by the test suite.

## Dependency ordering

A session can select only the top-level services it cares about. `topological_service_order` expands all transitive dependencies, validates references, rejects cycles, and returns a deterministic dependency-first order.

Phase 4 then starts every currently eligible service in parallel, capped to a small worker pool. A service becomes eligible only after all its dependencies are in the ready set.

## Readiness

Switchyard currently supports four readiness primitives:

- `process` — the process remains alive through the startup guard period
- `port` — a local TCP connection succeeds to `host:port`
- `http` — a configured HTTP/HTTPS endpoint returns a successful response
- `delay` — a configured amount of startup time elapses while the process remains alive

Readiness is separate from command launch. Starting a process does not imply that downstream services may begin.

## Preflight

`session_preflight` evaluates conditions that can be checked before commands are launched:

- dependency-graph validity
- project path availability
- executable resolution
- environment-profile inheritance requirements
- readiness syntax
- duplicate claimed readiness ports
- ports already listening before startup

Checks are classified as `PASS`, `WARN`, or `ERROR`. Errors block startup; warnings remain visible and require an explicit decision in the desktop UI.

## Restart behavior

Runtime policy supports:

- `never`
- `on_failure`
- `always`

Restart attempts are bounded. Delay grows exponentially from the configured base backoff up to the configured maximum. Once restart attempts are exhausted, normal service failure policy applies.

## Failure behavior

A service can use:

- `stop_dependents` — exhausted failure stops currently running transitive dependents
- `continue` — the controller records degradation without cascading a stop

Dependencies that fail before becoming ready block downstream startup.

## Desktop layering

Phase 4 preserves the stable Phase 3 UI shell in `switchyard_base.py`. The packaged entry point, `switchyard_desktop.pyw`, subclasses that shell and adds resilient runtime controls.

This keeps the large command-center interface stable while environment, preflight, and resilience behavior can evolve as a separate layer.

## Local-first boundary

Switchyard launches local commands and reads metadata from folders explicitly added by the user. It does not upload repository contents, require a hosted workspace, or depend on a telemetry service.

HTTP readiness performs only the configured probe; it is not a crawler or remote monitoring service.
