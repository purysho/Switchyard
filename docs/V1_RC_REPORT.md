# Switchyard V1 release-candidate report

This report records the release-candidate gate added during V1 hardening. It is evidence for the packaged artifact path, not a substitute for the remaining interactive Windows UI checks in `V1_RELEASE_CHECKLIST.md`.

## Candidate pipeline

The release-candidate CI pipeline now performs all of the following before V1 can be considered for tagging:

1. Run the full unit and destructive/hardening suite on Ubuntu with Python 3.10 and 3.12.
2. Run the same suite on Windows with Python 3.10 and 3.12.
3. Run `tools/v1_smoke.py` in every matrix job against a disposable profile.
4. Compile every `switchyard_*.py` module plus `switchyard_desktop.pyw`.
5. Build the one-file Windows GUI executable.
6. Launch the newly built executable with `--smoke-test`.
7. Generate `Switchyard.exe.sha256`.
8. Upload the executable and checksum as the `Switchyard-windows` artifact.
9. Start a separate Windows job that downloads that uploaded artifact from GitHub Actions.
10. Recompute the executable SHA-256, compare it with the downloaded checksum file, reject unexpectedly small executables, and launch the exact downloaded executable with `--smoke-test`.

This final download-and-run step is intentionally separate from the build job: it verifies the artifact users would actually retrieve rather than only the file that existed inside the builder workspace.

## Verified candidate evidence

The first complete run of the downloaded-artifact gate was GitHub Actions run `35137424117` on commit `54443f045b6ea3feed3859a51d498a270a228893`.

All four test jobs, the Windows build job, and the post-upload `artifact-verification` job completed successfully.

The uploaded artifact was independently downloaded after CI. Its GitHub artifact ZIP digest was:

```text
sha256:7155faf692ffc22a00139b634d9be719570bdec9e5367a9cf00f9f2507f9e117
```

The ZIP contained:

```text
Switchyard.exe
Switchyard.exe.sha256
```

The executable was 12,748,770 bytes and its bundled checksum matched an independent recomputation:

```text
9dc5865c91a8a1f111efeea207ea7aebffcdac8a6fd628a6e622af40ad77e568  Switchyard.exe
```

Static PE inspection identified it as an x86-64 Windows GUI executable. It is currently unsigned; the PE security directory is empty. This is not treated as a functional V1 blocker, but it should be understood as a possible Windows reputation/SmartScreen friction point until code signing is introduced.

## Repository release material

The candidate branch contains the expected public release material:

- `README.md`
- `SECURITY.md`
- `LICENSE`
- `CHANGELOG.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `docs/V1_RELEASE_CHECKLIST.md`
- interface preview artwork
- Windows build workflow
- tagged release workflow with executable checksum generation

## What remains deliberately manual

The remaining release gate requires a normal interactive Windows desktop. It validates behavior that cannot be established by headless CI alone:

- first visible launch and empty-state presentation
- window title/icon and resizing at 100% and 150% display scaling
- Task Manager force-kill followed by the visible recovery flow
- **Cancel/inspect**, **Forget**, and orphan termination + restore interactions
- visible persistence/recovery messaging after intentionally damaged files
- installed Purysho ecosystem handoffs
- template/snapshot workflows through the actual desktop controls

The underlying mechanics for these paths are covered by automated tests, but the V1 tag should wait until the visible packaged experience has also been exercised on an interactive Windows machine.

## Release rule

Do not tag `v1.0.0` if the final exact release commit has a failing CI gate or if the interactive Windows pass finds reproducible data loss, false readiness, orphan process trees, unbounded restarts, silent schema downgrade, packaged-launch failure, or a first-run crash.
