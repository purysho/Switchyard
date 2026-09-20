"""Post-v1.0 observation probe.

This is intentionally narrower than the full unit suite. It exercises failure
diagnostics a real user is likely to encounter and records a lightweight
workspace-intelligence performance baseline without touching ~/.switchyard.
"""

from __future__ import annotations

import json
import os
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from switchyard_core import (
    ReadinessCheck,
    Service,
    WorkspaceSession,
    WorkspaceState,
    detect_project,
    new_project,
    project_snapshot,
)
from switchyard_runtime import (
    EnvironmentProfile,
    ResilientSessionController,
    RuntimeSettings,
    session_preflight,
)


def wait_until(predicate, timeout=5.0, interval=.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


class _AcceptAndClose(socketserver.BaseRequestHandler):
    def handle(self):
        return


def has_error(checks, name):
    return any(check.level == "ERROR" and check.name == name for check in checks)


def main() -> int:
    report: dict[str, object] = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "checks": {},
        "performance": {},
    }

    with tempfile.TemporaryDirectory(prefix="switchyard-post-v1-") as raw:
        root = Path(raw)
        project_dir = root / "Messy Project – observation"
        project_dir.mkdir()

        # 2,000 ordinary files plus stack metadata. Ignored content should not
        # inflate the workspace snapshot.
        for folder_index in range(40):
            folder = project_dir / f"src-{folder_index:02d}"
            folder.mkdir()
            for file_index in range(50):
                (folder / f"file-{file_index:02d}.txt").write_text("x" * 64, encoding="utf-8")

        ignored = project_dir / "node_modules" / "package"
        ignored.mkdir(parents=True)
        for index in range(200):
            (ignored / f"ignored-{index}.js").write_text("ignored", encoding="utf-8")

        (project_dir / "package.json").write_text(json.dumps({
            "scripts": {"dev": "vite", "test": "echo test", "build": "vite build"},
            "dependencies": {"react": "19.0.0"},
        }), encoding="utf-8")
        (project_dir / "requirements.txt").write_text("", encoding="utf-8")
        (project_dir / "Cargo.toml").write_text("[package]\nname='observation'\nversion='0.0.0'\n", encoding="utf-8")

        project = new_project(project_dir, "Messy observation")

        started = time.perf_counter()
        snapshot = project_snapshot(project)
        snapshot_seconds = time.perf_counter() - started

        started = time.perf_counter()
        detected = detect_project(project.path)
        detect_seconds = time.perf_counter() - started

        assert snapshot["files"] == 2003, snapshot
        assert {"Node.js", "React", "Python", "Rust"}.issubset(set(detected["stacks"])), detected
        report["performance"] = {
            "ordinary_files": 2003,
            "ignored_files": 200,
            "snapshot_seconds": round(snapshot_seconds, 4),
            "detection_seconds": round(detect_seconds, 4),
        }

        checks = report["checks"]
        assert isinstance(checks, dict)

        # Missing/renamed project.
        missing_dir = root / "removed-project"
        missing_dir.mkdir()
        missing_project = new_project(missing_dir, "Removed")
        missing_dir.rmdir()
        missing_service = Service("missing-project", missing_project.id, "Missing project", f'"{sys.executable}" -c "print(1)"')
        missing_session = WorkspaceSession("missing-session", "Missing project", [missing_service.id])
        missing_state = WorkspaceState([missing_project], missing_project.id, services=[missing_service], sessions=[missing_session])
        missing_checks = session_preflight(missing_state, missing_session, RuntimeSettings())
        assert has_error(missing_checks, "Project")
        checks["missing_project"] = "PASS"

        # Occupied readiness port must fail closed.
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _AcceptAndClose)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            occupied = Service(
                "occupied",
                project.id,
                "Occupied port",
                f'"{sys.executable}" -c "import time; time.sleep(1)"',
                readiness=ReadinessCheck("port", str(server.server_address[1]), 1.0),
            )
            occupied_session = WorkspaceSession("occupied-session", "Occupied", [occupied.id])
            occupied_state = WorkspaceState([project], project.id, services=[occupied], sessions=[occupied_session])
            occupied_checks = session_preflight(occupied_state, occupied_session, RuntimeSettings())
            assert has_error(occupied_checks, "Port already open")
            checks["occupied_port"] = "PASS"
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

        # Missing inherited environment variable.
        env_service = Service("env", project.id, "Needs token", f'"{sys.executable}" -c "print(1)"')
        env_session = WorkspaceSession("env-session", "Environment", [env_service.id])
        env_state = WorkspaceState([project], project.id, services=[env_service], sessions=[env_session])
        env_key = "SWITCHYARD_OBSERVATION_MISSING_VALUE"
        os.environ.pop(env_key, None)
        settings = RuntimeSettings(
            profiles=[EnvironmentProfile("profile", "Observation", {}, [env_key])],
            session_profiles={env_session.id: "profile"},
        )
        env_checks = session_preflight(env_state, env_session, settings)
        assert has_error(env_checks, "Environment")
        checks["missing_environment"] = "PASS"

        # Malformed readiness configuration.
        invalid = Service(
            "invalid",
            project.id,
            "Invalid readiness",
            f'"{sys.executable}" -c "print(1)"',
            readiness=ReadinessCheck("port", "not-a-port", 1.0),
        )
        invalid_session = WorkspaceSession("invalid-session", "Invalid", [invalid.id])
        invalid_state = WorkspaceState([project], project.id, services=[invalid], sessions=[invalid_session])
        invalid_checks = session_preflight(invalid_state, invalid_session, RuntimeSettings())
        assert has_error(invalid_checks, "Readiness")
        checks["invalid_readiness"] = "PASS"

        # Missing executable: advisory command resolution is allowed, but launch
        # must fail cleanly and leave no live process.
        absent = Service(
            "absent",
            project.id,
            "Missing executable",
            "switchyard-command-that-does-not-exist-4f391c",
            readiness=ReadinessCheck("process", "", .5),
            failure_policy="continue",
        )
        absent_session = WorkspaceSession("absent-session", "Absent command", [absent.id])
        absent_state = WorkspaceState([project], project.id, services=[absent], sessions=[absent_session])
        absent_controller = ResilientSessionController(absent_state, absent_session, RuntimeSettings())
        absent_controller.start()
        try:
            assert wait_until(lambda: absent_controller.status in {"DEGRADED", "FAILED"}, timeout=4)
            proc = absent_controller.processes.get(absent.id)
            assert proc is None or not proc.running
        finally:
            absent_controller.stop()
        checks["missing_executable"] = "PASS"

        # A broken custom cwd should be caught before launch. Relative cwd values
        # are expected to be project-relative.
        broken = Service(
            "broken-cwd",
            project.id,
            "Broken cwd",
            f'"{sys.executable}" -c "print(1)"',
            cwd="does-not-exist",
        )
        broken_session = WorkspaceSession("broken-cwd-session", "Broken cwd", [broken.id])
        broken_state = WorkspaceState([project], project.id, services=[broken], sessions=[broken_session])
        broken_checks = session_preflight(broken_state, broken_session, RuntimeSettings())
        assert has_error(broken_checks, "Working directory"), broken_checks
        checks["broken_working_directory"] = "PASS"

    Path("post_v1_observation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
