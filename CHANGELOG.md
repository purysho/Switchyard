# Changelog

## Unreleased — Phase 2: Workspace Intelligence

### Added
- Project stack/framework detection from common manifests and repository evidence.
- Suggested run configurations derived from detected project tasks.
- Expanded Git snapshot: dirty count, upstream, ahead/behind, latest commit and origin remote.
- Project health checks for paths, Git state, command availability and likely development ports.
- Persistent run history with PID, timestamps, exit status and duration.
- Project tags, pin state and last-opened metadata.
- Versioned workspace state with backwards-compatible loading of V1 state files.

### Improved
- Managed process logging is bounded to avoid unbounded memory growth.
- Project snapshots ignore additional generated/build directories.

## 0.1.0
- Initial local developer workspace V1.
- Project registry, notes, run configurations, managed processes, live logs and local-port visibility.
