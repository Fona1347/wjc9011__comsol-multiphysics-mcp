"""Create a COMSOL cube and export a topology acceptance report."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.topology_utils import unit_cube_topology  # noqa: E402


MODEL_NAME = "cube_topology_acceptance"
MODEL_DIR = PROJECT_ROOT / "comsol_models" / MODEL_NAME
DEV_LOG_DIR = PROJECT_ROOT / "dev_log"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def validate_cube_report(topology: dict) -> dict:
    """Validate topology invariants for a single 1 m cube."""
    errors: list[str] = []
    counts = topology.get("counts", {})
    expected = {"domains": 1, "boundaries": 6, "edges": 12, "vertices": 8}
    for key, value in expected.items():
        if counts.get(key) != value:
            errors.append(f"Expected {key}={value}, got {counts.get(key)}.")

    for boundary in topology.get("boundaries", {}).values():
        if len(boundary.get("vertices", [])) != 4:
            errors.append(f"Boundary {boundary.get('id')} does not have 4 vertices.")
        if len(boundary.get("edges", [])) != 4:
            errors.append(f"Boundary {boundary.get('id')} does not have 4 edges.")
        if boundary.get("adjacent_domains") != [1]:
            errors.append(
                f"Boundary {boundary.get('id')} adjacent_domains is "
                f"{boundary.get('adjacent_domains')}, expected [1]."
            )
        if boundary.get("is_exterior") is not True:
            errors.append(f"Boundary {boundary.get('id')} is not marked exterior.")

    for edge in topology.get("edges", {}).values():
        if len(edge.get("vertices", [])) != 2:
            errors.append(f"Edge {edge.get('id')} does not have 2 vertices.")

    domain = topology.get("domains", {}).get("1", {})
    if len(domain.get("boundaries", [])) != 6:
        errors.append("Domain 1 is not bounded by 6 boundaries.")

    expected_bbox = {"x": [0.0, 1.0], "y": [0.0, 1.0], "z": [0.0, 1.0]}
    if topology.get("global_bbox") != expected_bbox:
        errors.append(f"Expected global bbox {expected_bbox}, got {topology.get('global_bbox')}.")

    found_tags = {
        tag
        for boundary in topology.get("boundaries", {}).values()
        for tag in boundary.get("position_tags", [])
    }
    expected_tags = {"min_x", "max_x", "min_y", "max_y", "min_z", "max_z"}
    if found_tags != expected_tags:
        errors.append(f"Expected plane tags {sorted(expected_tags)}, got {sorted(found_tags)}.")

    return {"passed": not errors, "errors": errors}


def comsol_startup_preflight() -> dict:
    """Check whether this process should attempt to start COMSOL."""
    home = Path.home()
    log_dir = home / ".comsol" / "v64" / "tomcat" / "logs"
    probe = log_dir / f"codex_preflight_{os.getpid()}.tmp"
    result = {
        "success": True,
        "log_dir": str(log_dir),
        "warnings": [],
        "errors": [],
    }
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        probe.write_text("preflight", encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        result["success"] = False
        result["errors"].append(
            "Cannot write COMSOL Tomcat log directory before mph.start()."
        )
        result["errors"].append(str(exc))
    return result


def write_preflight_blocked_report(preflight: dict) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    DEV_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "success": False,
        "stage": "preflight_blocked",
        "preflight": preflight,
        "message": (
            "COMSOL startup was not attempted because preflight detected an "
            "environment/permission issue. Use --force-comsol to bypass."
        ),
    }
    report_path = MODEL_DIR / f"preflight_blocked_{timestamp}.json"
    dev_log_path = DEV_LOG_DIR / f"{timestamp}_cube_topology_preflight_blocked.json"
    _write_json(report_path, report)
    _write_json(dev_log_path, report)
    print("COMSOL preflight blocked startup.")
    print(f"Preflight report: {report_path}")
    print(f"Dev log: {dev_log_path}")


def run_offline_fixture() -> None:
    """Write and validate the deterministic cube topology without COMSOL."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    topology = unit_cube_topology()
    validation = validate_cube_report(topology)
    report = {
        "model": "unit_cube_fixture",
        "timestamp": timestamp,
        "mode": "offline_fixture",
        "topology": topology,
        "acceptance": validation,
        "note": "This validates MCP topology logic without starting COMSOL.",
    }
    report_path = MODEL_DIR / f"offline_topology_report_{timestamp}.json"
    _write_json(report_path, report)
    print(f"Offline report: {report_path}")
    if not validation["passed"]:
        print("Offline acceptance failed:")
        for error in validation["errors"]:
            print(f"  - {error}")
        raise SystemExit(1)
    print("Offline acceptance passed.")


def run_worker() -> None:
    import mph
    from src.tools.geometry import _analyze_geometry_topology

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("Starting COMSOL...")
    client = mph.start(cores=2)
    model = client.create(MODEL_NAME)
    jm = model.java

    print("Creating 1 m cube...")
    comp = jm.component().create("comp1", True)
    geom = comp.geom().create("geom1", 3)
    block = geom.feature().create("blk1", "Block")
    block.set("pos", ["0", "0", "0"])
    block.set("size", ["1[m]", "1[m]", "1[m]"])
    geom.run()

    print("Analyzing topology...")
    topology = _analyze_geometry_topology(model, "geom1", "comp1")
    validation = validate_cube_report(topology)
    report = {
        "model": MODEL_NAME,
        "timestamp": timestamp,
        "topology": topology,
        "acceptance": validation,
    }

    report_path = MODEL_DIR / f"topology_report_{timestamp}.json"
    model_path = MODEL_DIR / f"{MODEL_NAME}_{timestamp}.mph"
    latest_path = MODEL_DIR / f"{MODEL_NAME}_latest.mph"
    _write_json(report_path, report)
    model.save(str(model_path))
    model.save(str(latest_path))

    print(f"Report: {report_path}")
    print(f"Model:  {model_path}")
    if not validation["passed"]:
        print("Acceptance failed:")
        for error in validation["errors"]:
            print(f"  - {error}")
        raise SystemExit(1)
    print("Acceptance passed.")


def run_with_timeout(timeout_seconds: int) -> None:
    """Run the COMSOL workflow in a child process with a hard timeout."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    DEV_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )

    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        cleanup = {}
        if sys.platform == "win32":
            kill_command = ["taskkill", "/PID", str(process.pid), "/T", "/F"]
            try:
                cleanup_proc = subprocess.run(
                    kill_command,
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                cleanup = {
                    "command": kill_command,
                    "returncode": cleanup_proc.returncode,
                    "stdout": cleanup_proc.stdout,
                    "stderr": cleanup_proc.stderr,
                }
            except subprocess.TimeoutExpired as cleanup_exc:
                cleanup = {
                    "command": kill_command,
                    "timeout": True,
                    "stdout": cleanup_exc.stdout or "",
                    "stderr": cleanup_exc.stderr or "",
                }
                try:
                    process.kill()
                except Exception as kill_exc:
                    cleanup["process_kill_error"] = str(kill_exc)
        else:
            process.kill()
            cleanup = {"method": "process.kill"}
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception as kill_exc:
                cleanup["second_kill_error"] = str(kill_exc)
            stdout, stderr = "", ""
            cleanup["communicate_timeout_after_kill"] = True
        report = {
            "success": False,
            "stage": "timeout",
            "timeout_seconds": timeout_seconds,
            "command": command,
            "stdout": stdout or "",
            "stderr": stderr or "",
            "cleanup": cleanup,
            "message": (
                "COMSOL acceptance worker exceeded timeout. This usually "
                "means mph.start(), COMSOL server startup, license checkout, "
                "or user-profile logging is blocked."
            ),
        }
        report_path = MODEL_DIR / f"timeout_report_{timestamp}.json"
        dev_log_path = DEV_LOG_DIR / f"{timestamp}_cube_topology_acceptance_timeout.json"
        payload = json.dumps(report, indent=2, ensure_ascii=False)
        report_path.write_text(payload, encoding="utf-8")
        dev_log_path.write_text(payload, encoding="utf-8")
        print(f"Acceptance timed out after {timeout_seconds}s.")
        print(f"Timeout report: {report_path}")
        print(f"Dev log: {dev_log_path}")
        raise SystemExit(124)

    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, file=sys.stderr, end="")
    if process.returncode != 0:
        report = {
            "success": False,
            "stage": "worker_failed",
            "returncode": process.returncode,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
        }
        report_path = MODEL_DIR / f"failure_report_{timestamp}.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Failure report: {report_path}")
        raise SystemExit(process.returncode)


def main() -> None:
    timeout_seconds = 300
    if "--worker" in sys.argv:
        run_worker()
        return
    if "--offline-fixture" in sys.argv:
        run_offline_fixture()
        return
    if "--timeout" in sys.argv:
        index = sys.argv.index("--timeout")
        try:
            timeout_seconds = int(sys.argv[index + 1])
        except (IndexError, ValueError):
            print("--timeout requires an integer number of seconds.", file=sys.stderr)
            raise SystemExit(2)
    if "--force-comsol" not in sys.argv:
        preflight = comsol_startup_preflight()
        if not preflight["success"]:
            write_preflight_blocked_report(preflight)
            raise SystemExit(125)
    run_with_timeout(timeout_seconds)


if __name__ == "__main__":
    main()
