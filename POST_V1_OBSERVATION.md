# Switchyard post-v1.0 observation

Switchyard v1.0.0 is released. This document separates post-release observation from feature planning.

## Published artifact baseline

### Current release — v1.0.1

- Windows asset: `Switchyard.exe`
- Published size: `12,748,403` bytes
- SHA-256: `17b9c92242750e525cc54c22051b4657cc17570ad3e028e6af025eee2231bacb`
- Release asset is currently unsigned.
- Patch: relative custom working directories now resolve from the project root, and unavailable custom working directories block in Preflight.

### Original release — v1.0.0

- Published size: `12,748,460` bytes
- SHA-256: `1725944a25075cb18ab20c390dbcb0fe2e5c20f59c2b8b5355df0704d5814ea1`

The `Post-v1 observation` workflow downloads the current public release assets, verifies the checksum file and known release digest, then runs the packaged `--smoke-test` probe.

## Latest automated observation

The verified v1.0.1 observation run passed on Windows and Ubuntu.

Synthetic workspace baseline:

| Runner | Files scanned | Ignored files | Snapshot | Stack/task detection |
| --- | ---: | ---: | ---: | ---: |
| Ubuntu / Python 3.12.14 | 2,003 | 200 | 0.0168 s | 0.0006 s |
| Windows / Python 3.12.10 | 2,003 | 200 | 0.0658 s | 0.0014 s |

These hosted-runner measurements are observation data, not performance thresholds. No material workspace-intelligence bottleneck was reproduced in this probe.

All focused failure probes passed: missing project, occupied readiness port, missing inherited environment variable, malformed readiness configuration, missing executable cleanup, and unavailable custom working directory.

## Observation focus

Treat v1.0.0 as a real user would and record only concrete defects/regressions:

- first launch and project registration
- workspace intelligence on large or messy repositories
- run configuration start / stop / restart
- service dependency topology
- preflight diagnostics
- process, port, HTTP and delay readiness
- live logs
- restart policy and failure cascades
- crash recovery
- state persistence, rotating backups and snapshots
- session template import/export
- optional ecosystem handoffs

## Failure cases

The observation probe and existing hardening tests cover:

- missing executable
- occupied readiness port
- missing or moved project directory
- missing inherited environment variables
- malformed readiness configuration
- dependency failure and cascade behavior
- bounded restarts
- process-tree shutdown
- corrupt state and backup recovery
- future-schema preservation
- concurrent persistence/export writes
- custom working-directory validation

## v1.0.1 outcome

The post-v1.0 pass reproduced one bounded shipped defect: custom relative working directories were resolved from Switchyard's launch directory, and missing custom working directories were not blocked during Preflight.

The fix is covered by regression tests and shipped in **v1.0.1**. No additional product defect was promoted into the patch.

Further fixes should require a new concrete reproduction. Feature requests and capability expansion belong in v1.1 planning.

## Known non-regressions

- The Windows executable is not Authenticode-signed. SmartScreen/reputation warnings are expected until code signing is introduced.
- Command resolution is advisory because shell commands and environment-specific launchers cannot always be proven resolvable before execution.
