# Switchyard V1 release checklist

This checklist is the final gate before creating a V1 tag. Automated items must be green on the exact release commit. Manual items should be run against the packaged Windows executable on a disposable Switchyard profile.

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

The release-candidate evidence is recorded in [V1_RC_REPORT.md](V1_RC_REPORT.md).

## Clean first-run test

Use a disposable profile. If an existing `%USERPROFILE%\.switchyard` directory matters, back it up rather than deleting it.

- [ ] Launch the packaged executable with no existing Switchyard state directory.
- [ ] Dashboard opens without an exception, recovery prompt, phantom project, or phantom session.
- [ ] Add a project whose path contains spaces and at least one non-ASCII character.
- [ ] Restart Switchyard and confirm the project, selected project, notes/tags and detected metadata reload correctly.
- [ ] Confirm no network/account/telemetry setup is required.

## Core workspace journey

- [ ] Create a run configuration, start it, observe output, stop it, then run it again.
- [ ] Create at least two services with a dependency and a workspace session.
- [ ] Run Preflight and confirm the dependency graph and project checks are understandable.
- [ ] Start the session and confirm dependencies become ready before dependents launch.
- [ ] Stop the session and confirm the topology stops in reverse dependency order.
- [ ] Repeat start/stop/start quickly and confirm no duplicate or stale process appears.
- [ ] Try to start an already-running session and confirm it is rejected without disturbing the live process.

## Failure and destructive-state checks

The same mechanics below have automated destructive coverage. These boxes remain manual because the final release gate also checks how the packaged Windows UI presents and recovers from those states.

- [ ] Configure a service with a missing executable. Confirm failure is explicit and no process remains running.
- [ ] Remove/rename a registered project directory. Confirm Preflight blocks startup.
- [ ] Occupy a configured readiness port with another process. Confirm startup is blocked rather than producing a false READY state.
- [ ] Configure two independent services to fail together. Confirm a shared dependent never starts.
- [ ] Configure a bounded restart policy, force a failure, then stop/restart the session while backoff is pending. Confirm the old restart never wakes into the new run.
- [ ] Start a service that spawns a child process, stop it from Switchyard, and confirm the process tree is gone.
- [ ] While a workspace is running, force-kill Switchyard from Task Manager. Relaunch and verify the recovery prompt correctly identifies the prior session/process state.
- [ ] At the recovery prompt, test **Cancel/inspect** and confirm unresolved recovery is still offered after another forced crash.
- [ ] Test **Forget** and confirm the prior recovery state is intentionally cleared.
- [ ] Test orphan termination + restore and confirm the old process tree is stopped before the session is restarted.

## Persistence and evidence preservation

Perform these only against a disposable profile. The persistence engine has automated destructive coverage for each case; the boxes below remain a packaged-UI confirmation pass.

- [ ] Corrupt `state.json` while valid rotating backups exist. Relaunch and confirm Switchyard recovers the newest valid generation and preserves the damaged file as evidence.
- [ ] Corrupt the newest backup as well. Confirm recovery falls through to an older valid generation.
- [ ] Place a future-version schema in `state.json` or `runtime.json`. Confirm Switchyard does not overwrite it silently.
- [ ] Confirm inherited secret values are absent from `runtime.json`, backups, templates and snapshots.
- [ ] Export a busy service log and confirm the result is complete/readable after repeated exports.

## Ecosystem and portability

- [ ] Open the Ecosystem view with BLACKBOX, Needle, Relay and Pulse unavailable. Confirm Switchyard degrades gracefully to repository links.
- [ ] With one compatible tool installed, verify a handoff opens the expected project/service context.
- [ ] Export a session template and confirm it contains no environment values.
- [ ] Import that template into a clean disposable profile and verify project mapping is explicit.
- [ ] Save and restore a session snapshot and confirm runtime policy metadata is restored without secret values.

## Packaging and release

- [x] Download the Windows artifact from the final candidate CI run rather than using a locally built copy.
- [x] Independently compare the downloaded `Switchyard.exe` against the bundled SHA-256 checksum.
- [ ] Launch that artifact on a normal interactive Windows desktop and repeat the clean first-run test.
- [ ] Check the executable icon, window title and basic resizing at 100% and 150% display scaling.
- [x] Confirm README instructions match the packaged behavior and CI-tested source versions.
- [x] Confirm `SECURITY.md`, `LICENSE`, architecture documentation and changelog are present.
- [ ] Create the V1 tag only after every blocking item above is complete.

## Release decision

A V1 release is blocked by any reproducible data loss, silent schema downgrade, orphan process tree, unbounded restart loop, false readiness, packaged-launch failure, or first-run crash. Cosmetic issues can be documented for a follow-up only when they do not obscure state, failure, recovery or destructive actions.

The automated and downloaded-artifact gates are green. The remaining unchecked items require an interactive Windows desktop because they validate visible UI behavior, display scaling, Task Manager force-kill recovery, and real handoff interaction rather than only the underlying model/runtime behavior.
