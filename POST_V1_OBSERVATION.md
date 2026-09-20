# Switchyard post-v1.0 observation

Switchyard v1.0.0 is released. This document separates post-release observation from feature planning.

## Published artifact baseline

- Release: `v1.0.0`
- Windows asset: `Switchyard.exe`
- Published size: `12,748,460` bytes
- SHA-256: `1725944a25075cb18ab20c390dbcb0fe2e5c20f59c2b8b5355df0704d5814ea1`
- Release asset is currently unsigned.

The `Post-v1 observation` workflow downloads the public release assets, verifies the checksum file and known release digest, then runs the packaged `--smoke-test` probe.

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

## v1.0.1 gate

A v1.0.1 candidate must be:

1. reproducible against v1.0.0;
2. a shipped defect or release/installation regression;
3. bounded enough to fix without adding a new capability;
4. covered by a regression test.

Feature requests and capability expansion belong in v1.1 planning.

## Known non-regressions

- The Windows executable is not Authenticode-signed. SmartScreen/reputation warnings are expected until code signing is introduced.
- Command resolution is advisory because shell commands and environment-specific launchers cannot always be proven resolvable before execution.
