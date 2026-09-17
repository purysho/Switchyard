# Switchyard V1 release checklist

This checklist records the final gate for Switchyard V1. Automated items must be green on the exact release commit. Manual acceptance is performed against the packaged Windows executable on a disposable Switchyard profile.

## Automated gates

- [x] Unit + hardening tests pass on Ubuntu / Python 3.10.
- [x] Unit + hardening tests pass on Ubuntu / Python 3.12.
- [x] Unit + hardening tests pass on Windows / Python 3.10.
- [x] Unit + hardening tests pass on Windows / Python 3.12.
- [x] `python tools/v1_smoke.py` passes on all four test jobs.
- [x] Every `switchyard_*.py` module and `switchyard_desktop.pyw` compiles successfully.
- [x] `build-windows.ps1` produces `dist/Switchyard.exe`.
- [x] The packaged executable exits successfully with `--smoke-test`.
- [x] The CI candidate includes `Switchyard.exe.sha256`, and a second Windows job downloads the uploaded artifact, verifies that checksum, and launches that exact downloaded executable with `--smoke-test`.
- [x] Release workflow generates `Switchyard.exe.sha256` before upload.
- [x] Final release-soak jobs repeat the complete test suite three times on both Ubuntu and Windows.
- [x] Final release-soak jobs repeat the first-run smoke test five times on both Ubuntu and Windows.

The release-candidate evidence is recorded in [V1_RC_REPORT.md](V1_RC_REPORT.md).

## Clean first-run acceptance

- [x] Launch the packaged executable with no existing Switchyard state directory.
- [x] Dashboard opens without an exception, recovery prompt, phantom project, or phantom session.
- [x] Add a project whose path contains spaces and a non-ASCII character.
- [x] Restart Switchyard and confirm project state reloads correctly.
- [x] Confirm no network/account/telemetry setup is required.

## Core workspace acceptance

- [x] Create a run configuration, start it, observe output, stop it, then run it again.
- [x] Create at least two services with a dependency and a workspace session.
- [x] Run Preflight and confirm the dependency graph/project checks are understandable.
- [x] Start the session and confirm dependencies become ready before dependents launch.
- [x] Stop the session and confirm the topology stops cleanly.
- [ ] Repeat start/stop/start rapidly as a manual stress check. Automated lifecycle coverage is green.
- [ ] Try to start an already-running session manually. Automated duplicate-start coverage is green.

## Failure and destructive-state coverage

The mechanics below are release-blocking, but each is satisfied by automated destructive coverage unless marked as a visible packaged-UI acceptance item.

- [ ] Missing executable — covered by automated lifecycle hardening.
- [ ] Missing/renamed project directory — covered by automated preflight/lifecycle hardening.
- [ ] Preoccupied readiness port — covered by automated fail-closed readiness tests.
- [ ] Concurrent independent service failures — covered by automated dependency-failure tests.
- [ ] Restart backoff interrupted by stop/restart — covered by generation-scoped restart tests.
- [ ] Spawned child process-tree shutdown — covered by real process-tree tests on CI.
- [x] Force-kill Switchyard from Task Manager and verify the recovery prompt identifies the prior runtime.
- [x] Test **Cancel/inspect** and confirm unresolved recovery is preserved.
- [x] Test **Forget** and confirm the prior recovery state is intentionally cleared.
- [x] Test orphan termination/restore behavior from the packaged UI.

## Persistence and evidence preservation

These cases are destructive and are covered automatically against disposable profiles; manual repetition is optional after the packaged first-run/recovery acceptance pass.

- [ ] Corrupt `state.json` with valid rotating backups — automated recovery coverage is green.
- [ ] Corrupt the newest backup as well — automated multi-generation fallback coverage is green.
- [ ] Future-version schema protection — automated preservation/rejection coverage is green.
- [ ] Confirm inherited secret values never persist — automated/runtime design coverage is green.
- [ ] Repeated busy-log export — automated atomic export coverage is green.

## Ecosystem and portability

- [x] Confirm ecosystem handoffs launch compatible installed tools or degrade gracefully when a tool is unavailable.
- [ ] Export/import a session template manually. Automated portability/secret-exclusion coverage is green.
- [ ] Save/restore a session snapshot manually. Automated snapshot coverage is green.

## Packaging and release

- [x] Download the Windows artifact from the final candidate CI run rather than using a locally built copy.
- [x] Independently compare the downloaded `Switchyard.exe` against the bundled SHA-256 checksum.
- [x] Launch that artifact on a normal interactive Windows desktop.
- [x] Check the executable/window presentation and resizing at 100% and 150% display scaling.
- [x] Confirm README instructions match the packaged behavior and CI-tested source versions.
- [x] Confirm `SECURITY.md`, `LICENSE`, architecture documentation and changelog are present.
- [x] Manual Windows acceptance reported passed on 2026-09-17.
- [x] Final cross-platform release soak completed successfully.

## Release decision

V1 is blocked by any reproducible data loss, silent schema downgrade, orphan process tree, unbounded restart loop, false readiness, packaged-launch failure, or first-run crash. Every blocking mechanism has automated destructive coverage, while the user-visible first-run, scaling, runtime, crash-recovery and ecosystem paths have also passed packaged Windows acceptance.

Unchecked items above are retained as optional/manual exploratory repetitions where an automated equivalent already passed; they are not unresolved release blockers.

**Decision: release gate passed for `v1.0.0`.**
