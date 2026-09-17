# Switchyard V1 release-candidate report

This report records the final V1 release-candidate evidence for Switchyard.

## Candidate pipeline

The V1 pipeline verifies the release path with all of the following:

1. Full unit and destructive/hardening suite on Ubuntu with Python 3.10 and 3.12.
2. The same suite on Windows with Python 3.10 and 3.12.
3. `tools/v1_smoke.py` against a disposable profile in every matrix job.
4. Compilation of every `switchyard_*.py` module plus `switchyard_desktop.pyw`.
5. One-file Windows GUI executable build.
6. Packaged executable launch with `--smoke-test`.
7. SHA-256 generation for the packaged executable.
8. Upload of the executable and checksum as a GitHub Actions artifact.
9. A separate Windows job that downloads that uploaded artifact.
10. Independent checksum recomputation and launch of the exact downloaded executable.
11. Final release-soak jobs that repeat the full test suite three times on both Windows and Ubuntu.
12. Final release-soak jobs that repeat the first-run smoke test five times on both Windows and Ubuntu.

The download-and-run verification is deliberately separate from the build job so the pipeline validates the artifact users would retrieve rather than only the copy inside the builder workspace.

## Automated evidence

The downloaded-artifact gate completed successfully in GitHub Actions, followed by a final release-soak run that also completed successfully on Windows and Ubuntu.

The V1 hardening suite covers corrupt state/runtime files, rotating backup fallback, future-schema protection, interrupted writes, Unicode/space-heavy paths, stale crash journals, orphan-process recovery, bounded log floods, bounded restart loops, dependency failure propagation, missing projects/executables, occupied readiness ports, rapid lifecycle transitions, concurrent failures and spawned process-tree shutdown.

The final Windows artifact path also verifies:

```text
Switchyard.exe
Switchyard.exe.sha256
```

The executable is a 64-bit Windows GUI PE. It is currently not Authenticode-signed. That is not treated as a functional V1 blocker, but it can cause Windows reputation/SmartScreen friction until code signing is introduced.

## Manual packaged Windows acceptance

On 2026-09-17 the packaged release candidate passed interactive Windows acceptance covering:

- clean first visible launch
- normal resizing and 100% / 150% display scaling
- project paths containing spaces/non-ASCII characters and persistence across restart
- run configuration start/stop/re-run behavior
- a simple dependency-based workspace session with preflight/start/stop
- Task Manager force-kill followed by crash-recovery presentation
- Cancel/inspect, Forget and orphan-recovery behavior
- ecosystem handoff behavior when companion tools are installed or unavailable

This manual pass complements the deeper destructive scenarios already covered automatically.

## Repository release material

The release candidate contains:

- `README.md`
- `SECURITY.md`
- `LICENSE`
- `CHANGELOG.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `docs/V1_RELEASE_CHECKLIST.md`
- this release-candidate report
- interface preview artwork
- Windows build workflow
- V1 release workflow with executable checksum generation and GitHub Release publication

## Release decision

The automated test matrix, repeated Windows/Linux soak, packaged executable verification, downloaded-artifact checksum/launch gate, and interactive Windows acceptance all passed.

No release-blocking data-loss, silent schema downgrade, orphan process-tree, unbounded restart, false-readiness, packaged-launch or first-run failure remains known at the V1 gate.

**Switchyard is cleared for `v1.0.0`.**
