# Switchyard architecture

Switchyard deliberately separates **stored intent** from **live runtime state**.

## Stored model

`WorkspaceState` is persisted as JSON and contains:

- `Project` — a local repository/folder and its human context
- `RunConfig` — a reusable command attached to one project
- `Service` — an operational command that can depend on other services
- `WorkspaceSession` — a named set of services to orchestrate together
- `RunRecord` — history for direct run configurations
- `SessionEvent` — the operational timeline for session orchestration

No process handles or volatile runtime objects are serialized.

## Runtime model

`ManagedProcess` owns one local subprocess and its bounded output buffer.

`SessionController` owns the runtime for one workspace session. It:

1. expands transitive dependencies
2. topologically sorts the selected graph
3. starts services serially in dependency order
4. evaluates readiness before advancing
5. tracks ready/failed state
6. applies dependent-stop behavior after unexpected failures
7. stops services in reverse topological order

This makes startup deterministic and keeps orchestration behavior testable outside the UI.

## Readiness

Phase 3 supports three local readiness primitives:

- `process` — the process remains alive through the startup guard period
- `port` — a local TCP connection succeeds to `host:port`
- `delay` — a configured amount of startup time elapses while the process remains alive

Future probes should build on this abstraction rather than special-casing frameworks in the orchestration engine.

## Failure behavior

A service can use:

- `stop_dependents` — failures stop currently running transitive dependents
- `continue` — the controller records degradation without cascading a stop

Dependencies that fail during startup block downstream services.

## Local-first boundary

Switchyard only stores configuration in `~/.switchyard/state.json` and launches local commands. Project detection reads manifest/file metadata inside folders the user added. No repository contents are uploaded by the application.
