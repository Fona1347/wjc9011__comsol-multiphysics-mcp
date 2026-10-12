"""Runtime identity and single-instance lock for the MCP server."""

from __future__ import annotations

import atexit
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(os.getenv("COMSOL_MCP_RUNTIME_DIR", PROJECT_ROOT / ".comsol_runtime"))
SERVER_INSTANCE_ID = uuid.uuid4().hex
SERVER_STARTED_AT = datetime.now().isoformat(timespec="seconds")
SERVER_PID = os.getpid()
TRANSPORT = "stdio"

LOCK_PATH = RUNTIME_ROOT / "server.lock"
STATE_PATH = RUNTIME_ROOT / "server_state.json"
_LOCK_HELD = False


class ServerAlreadyRunningError(RuntimeError):
    """Raised when another MCP server owns this runtime directory."""

    def __init__(self, lock_info: dict[str, Any]):
        self.lock_info = lock_info
        pid = lock_info.get("pid", "unknown")
        runtime_root = lock_info.get("runtime_root", str(RUNTIME_ROOT))
        super().__init__(
            f"HY-COMSOL-MCP server already running for runtime {runtime_root} "
            f"(pid={pid})."
        )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _lock_payload(status: str = "running") -> dict[str, Any]:
    return {
        "server_instance_id": SERVER_INSTANCE_ID,
        "pid": SERVER_PID,
        "started_at": SERVER_STARTED_AT,
        "transport": TRANSPORT,
        "runtime_root": str(RUNTIME_ROOT),
        "status": status,
    }


def acquire_server_lock() -> dict[str, Any]:
    """Acquire the per-runtime MCP server lock or fail if a live owner exists."""
    global _LOCK_HELD
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(_lock_payload("locked"), handle, indent=2)
            _LOCK_HELD = True
            atexit.register(release_server_lock)
            write_server_state(lock_status="locked")
            return {"acquired": True, "stale_reclaimed": False, **_lock_payload("locked")}
        except FileExistsError:
            lock_info = _read_json(LOCK_PATH)
            owner_pid = int(lock_info.get("pid") or 0)
            if owner_pid == SERVER_PID:
                _LOCK_HELD = True
                return {"acquired": True, "same_process": True, **_lock_payload("locked")}
            if owner_pid and _pid_alive(owner_pid):
                raise ServerAlreadyRunningError(lock_info)
            try:
                LOCK_PATH.unlink()
            except FileNotFoundError:
                pass
            except Exception as exc:
                raise RuntimeError(f"Failed to reclaim stale MCP lock {LOCK_PATH}: {exc}") from exc


def release_server_lock() -> None:
    """Release the runtime lock if this process still owns it."""
    global _LOCK_HELD
    if not _LOCK_HELD:
        return
    lock_info = _read_json(LOCK_PATH)
    if lock_info.get("server_instance_id") == SERVER_INSTANCE_ID:
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass
    _LOCK_HELD = False
    write_server_state(lock_status="stopped")


def write_server_state(lock_status: str = "running", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist observable server identity for diagnostics."""
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    state = {
        **_lock_payload(lock_status),
        "lock_path": str(LOCK_PATH),
        "state_path": str(STATE_PATH),
        "lock_held_by_this_process": _LOCK_HELD,
    }
    if extra:
        state.update(extra)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return state


def get_server_runtime_info() -> dict[str, Any]:
    """Return runtime identity and lock information for tool diagnostics."""
    lock_info = _read_json(LOCK_PATH)
    owner_pid = int(lock_info.get("pid") or 0)
    state = {
        **_lock_payload("running" if _LOCK_HELD else "unlocked"),
        "lock_path": str(LOCK_PATH),
        "state_path": str(STATE_PATH),
        "lock_exists": LOCK_PATH.exists(),
        "lock_held_by_this_process": _LOCK_HELD,
        "lock_owner_alive": _pid_alive(owner_pid) if owner_pid else False,
        "lock_owner": lock_info,
    }
    return state


def fail_fast_for_existing_server(error: ServerAlreadyRunningError) -> None:
    """Emit a clear startup error without writing to stdout MCP transport."""
    message = {
        "error": "HY_COMSOL_MCP_SERVER_ALREADY_RUNNING",
        "message": str(error),
        "current_pid": SERVER_PID,
        "current_instance_id": SERVER_INSTANCE_ID,
        "existing_lock": error.lock_info,
        "runtime_root": str(RUNTIME_ROOT),
    }
    print(json.dumps(message, ensure_ascii=False), file=sys.stderr)
