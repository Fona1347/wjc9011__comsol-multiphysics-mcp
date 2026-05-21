"""Session management tools for COMSOL MCP Server."""

import json
import os
import queue
import re
import socket
import subprocess
import threading
from datetime import datetime
from importlib import metadata
from pathlib import Path
from time import perf_counter
from typing import Any, Optional
from mcp.server.fastmcp import FastMCP
import mph

DEFAULT_COMSOL_ROOT = Path(r"D:\Softwares_02\COMSOL64\Multiphysics")
DEFAULT_COMSOL_JAVA_EXE = DEFAULT_COMSOL_ROOT / "java" / "win64" / "jre" / "bin" / "java.exe"
DEFAULT_COMSOL_JAVAC_EXE = DEFAULT_COMSOL_ROOT / "java" / "win64" / "jre" / "bin" / "javac.exe"
DEFAULT_COMSOL_BATCH_EXE = DEFAULT_COMSOL_ROOT / "bin" / "win64" / "comsolbatch.exe"
DEFAULT_COMSOL_COMPILE_EXE = DEFAULT_COMSOL_ROOT / "bin" / "win64" / "comsolcompile.exe"
DEFAULT_COMSOL_MPH_SERVER_EXE = DEFAULT_COMSOL_ROOT / "bin" / "win64" / "comsolmphserver.exe"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEV_LOG_DIR = PROJECT_ROOT / "dev_log"
DEFAULT_RUNTIME_ROOT = Path(os.getenv("COMSOL_MCP_RUNTIME_DIR", PROJECT_ROOT / ".comsol_runtime"))
DEFAULT_USER_COMSOL_ROOT = Path.home() / ".comsol" / "v64"
DEFAULT_USER_TOMCAT_LOG_DIR = DEFAULT_USER_COMSOL_ROOT / "tomcat" / "logs"
DEFAULT_START_TIMEOUT_SECONDS = 120
DEFAULT_START_MODE = "client-server"
DEFAULT_START_PORT = 0
DEFAULT_LOGIN_MODE = "auto"
ALLOWED_LOGIN_MODES = ("auto", "never", "force", "info")


class ComsolServerStartupTimeout(TimeoutError):
    """Raised when COMSOL server startup exceeds the MCP timeout."""

    def __init__(self, message: str, command: list[str], output_lines: list[str]):
        super().__init__(message)
        self.command = command
        self.output_lines = output_lines


class ComsolServerStartupError(RuntimeError):
    """Raised when COMSOL server exits before reporting a port."""

    def __init__(self, message: str, command: list[str], output_lines: list[str]):
        super().__init__(message)
        self.command = command
        self.output_lines = output_lines


def _runtime_path(env_name: str, default: Path) -> dict:
    """Resolve and report a COMSOL runtime executable path."""
    raw_path = os.getenv(env_name, str(default))
    path = Path(raw_path)
    return {
        "env": env_name,
        "path": str(path),
        "exists": path.exists(),
        "source": "environment" if os.getenv(env_name) else "default",
    }


def _package_version(package: str) -> str | None:
    """Return an installed Python package version if available."""
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _runtime_directories(root: Path | None = None) -> dict[str, Path]:
    """Return COMSOL runtime directories managed by this MCP server."""
    runtime_root = Path(root or DEFAULT_RUNTIME_ROOT)
    return {
        "root": runtime_root,
        "prefs": runtime_root / "prefs",
        "configuration": runtime_root / "configuration",
        "data": runtime_root / "data",
        "tmp": runtime_root / "tmp",
        "recovery": runtime_root / "recovery",
        "logs": runtime_root / "logs",
    }


def _comsol_server_arguments(runtime_root: Path | None = None) -> list[str]:
    """Build extra comsolmphserver arguments that redirect writable locations."""
    directories = _runtime_directories(runtime_root)
    return [
        "-prefsdir",
        str(directories["prefs"]),
        "-configuration",
        str(directories["configuration"]),
        "-data",
        str(directories["data"]),
        "-tmpdir",
        str(directories["tmp"]),
        "-recoverydir",
        str(directories["recovery"]),
    ]


def _parse_comsol_port(line: str) -> int | None:
    """Parse the COMSOL server port from a startup output line."""
    match = re.match(r"^COMSOL.* \(.*\) .*?(\d{4,5}).*$", line)
    return int(match.group(1)) if match else None


class ManagedComsolServer:
    """Small COMSOL server process wrapper with a hard startup timeout."""

    def __init__(
        self,
        cores: Optional[int] = None,
        version: Optional[str] = None,
        port: Optional[int] = None,
        timeout: int = DEFAULT_START_TIMEOUT_SECONDS,
        arguments: Optional[list[str]] = None,
        login_mode: str = DEFAULT_LOGIN_MODE,
    ):
        from mph import discovery

        if login_mode not in ALLOWED_LOGIN_MODES:
            raise ValueError(f"Unsupported COMSOL login mode: {login_mode}")
        backend = discovery.backend(version)
        server = [str(item) for item in backend["server"]]
        command = server + ["-login", login_mode, "-graphics", "-autosave", "off"]
        if cores:
            command += ["-np", str(cores)]
        if port is not None:
            command += ["-port", str(port)]
        command += arguments or []

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        self.command = command
        self.version = backend["name"]
        self.cores = cores
        self.port: Optional[int] = None
        self.output_lines: list[str] = []
        self._line_queue: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

        requested = port
        deadline = perf_counter() + timeout
        while perf_counter() < deadline:
            try:
                line = self._line_queue.get(timeout=0.2).strip()
            except queue.Empty:
                if self.process.poll() is not None:
                    break
                continue
            if line:
                self.output_lines.append(line)
            parsed_port = _parse_comsol_port(line)
            if parsed_port:
                if requested and parsed_port != requested:
                    self.stop(timeout=5)
                    raise RuntimeError(f"Server port is {parsed_port}, but {requested} was requested.")
                self.port = parsed_port
                return
            if self.process.poll() is not None:
                break

        if self.port is None:
            last_line = self.output_lines[-1] if self.output_lines else "no output"
            self.stop(timeout=5, force=True)
            if perf_counter() >= deadline:
                raise ComsolServerStartupTimeout(
                    f"COMSOL server failed to start within {timeout}s. Last output: {last_line}",
                    self.command,
                    self.output_lines[-20:],
                )
            raise ComsolServerStartupError(
                f"Starting COMSOL server failed. Last output: {last_line}",
                self.command,
                self.output_lines[-20:],
            )

    def _read_stdout(self) -> None:
        if self.process.stdout is None:
            return
        try:
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                self._line_queue.put(line)
        except Exception:
            return

    def running(self) -> bool:
        """Return whether the COMSOL server process is still running."""
        return self.process.poll() is None

    def stop(self, timeout: int = 20, force: bool = False) -> None:
        """Ask COMSOL server to stop, then terminate it if needed."""
        if not self.running():
            return
        if not force and self.process.stdin is not None:
            try:
                self.process.stdin.write("close\n")
                self.process.stdin.flush()
                self.process.wait(timeout=timeout)
                return
            except Exception:
                pass
        try:
            self.process.terminate()
            self.process.wait(timeout=timeout)
        except Exception:
            self.process.kill()


def _start_local_comsol_server(
    cores: Optional[int],
    version: Optional[str],
    port: Optional[int],
    timeout_seconds: int,
    arguments: list[str],
    login_mode: str = DEFAULT_LOGIN_MODE,
) -> ManagedComsolServer:
    """Start a local COMSOL server with MCP-owned timeout and cleanup."""
    return ManagedComsolServer(
        cores=cores,
        version=version,
        port=port,
        timeout=timeout_seconds,
        arguments=arguments,
        login_mode=login_mode,
    )


def _check_directory_access(path: Path, create: bool = False) -> dict[str, Any]:
    """Check whether a directory exists and can be written by the current process."""
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "created": False,
        "readable": False,
        "writable": False,
    }
    try:
        if create and not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            result["created"] = True
            result["exists"] = True
            result["is_dir"] = True
        if path.is_dir():
            next(path.iterdir(), None)
            result["readable"] = True
            probe = path / ".comsol_mcp_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            result["writable"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _directory_report(create_runtime_dirs: bool = False, runtime_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return write-readiness for COMSOL user and redirected runtime directories."""
    report = {
        "user_tomcat_logs": _check_directory_access(DEFAULT_USER_TOMCAT_LOG_DIR),
        "user_configuration": _check_directory_access(DEFAULT_USER_COMSOL_ROOT / "configuration"),
        "user_workspace": _check_directory_access(DEFAULT_USER_COMSOL_ROOT / "workspace"),
    }
    for name, directory in _runtime_directories(runtime_root).items():
        report[f"runtime_{name}"] = _check_directory_access(directory, create=create_runtime_dirs)
    return report


def _file_metadata(path: Path) -> dict[str, Any]:
    """Return non-sensitive file metadata without reading file contents."""
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "is_file": path.is_file(),
    }
    try:
        if path.is_file():
            stat = path.stat()
            result["size_bytes"] = stat.st_size
            result["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            result["readable"] = os.access(path, os.R_OK)
            result["writable"] = os.access(path, os.W_OK)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _login_properties_report(runtime_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Report COMSOL server login files without exposing credentials."""
    directories = _runtime_directories(runtime_root)
    candidates = {
        "runtime_prefs_login": directories["prefs"] / "login.properties",
        "runtime_root_login": directories["root"] / "login.properties",
        "user_root_login": DEFAULT_USER_COMSOL_ROOT / "login.properties",
        "user_prefs_login": DEFAULT_USER_COMSOL_ROOT / "prefs" / "login.properties",
    }
    return {name: _file_metadata(path) for name, path in candidates.items()}


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return whether a TCP port accepts connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _port_report(host: str = "127.0.0.1", start: int = 2036, count: int = 5) -> dict[int, bool]:
    """Return occupied status for the default COMSOL port range."""
    return {port: _port_open(host, port) for port in range(start, start + count)}


def _process_report() -> list[dict[str, Any]]:
    """Return a lightweight process snapshot for COMSOL-related processes."""
    try:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            (
                "Get-Process | "
                "Where-Object { $_.ProcessName -match 'python|comsolmphserver|java' } | "
                "Select-Object ProcessName,Id,Path,StartTime | ConvertTo-Json -Compress"
            ),
        ]
        process = subprocess.run(
            command,
            check=False,
            timeout=5,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if process.returncode != 0:
            return [{"error": process.stderr.strip() or f"exit code {process.returncode}"}]
        output = process.stdout.strip()
        if not output:
            return []
        data = json.loads(output)
        processes = data if isinstance(data, list) else [data]
        for item in processes:
            path = item.get("Path") if isinstance(item, dict) else None
            process_name = str(item.get("ProcessName", "")) if isinstance(item, dict) else ""
            try:
                resolved = Path(path).resolve() if path else None
                item["path_under_project"] = bool(resolved and PROJECT_ROOT in resolved.parents)
            except Exception:
                item["path_under_project"] = False
            item["cleanup_recommendation"] = (
                "manual_review"
                if process_name.lower() in ("comsolmphserver", "java")
                else "do_not_cleanup_from_preflight"
            )
        return processes
    except Exception as exc:
        return [{"error": f"{type(exc).__name__}: {exc}"}]


def _backend_report(version: Optional[str] = None) -> dict[str, Any]:
    """Return available MPh backend information without starting COMSOL."""
    try:
        from mph import discovery

        backends = discovery.find_backends()
        selected = discovery.backend(version)
        return {
            "success": True,
            "selected": _serialize_backend(selected),
            "available": [_serialize_backend(backend) for backend in backends],
        }
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def _serialize_backend(backend: dict[str, Any]) -> dict[str, Any]:
    """Convert MPh backend values to JSON-friendly data."""
    return {
        key: str(value) if isinstance(value, Path) else [str(item) for item in value] if isinstance(value, list) else value
        for key, value in backend.items()
    }


def _safe_client_info(client: mph.Client, server: Any = None, host: Optional[str] = None) -> dict[str, Any]:
    """Return client metadata without letting diagnostics fail the tool call."""
    info: dict[str, Any] = {
        "version": getattr(client, "version", None),
        "standalone": getattr(client, "standalone", None),
        "port": getattr(client, "port", None),
        "host": getattr(client, "host", host),
    }
    try:
        info["cores"] = client.cores
    except Exception as exc:
        info["cores_error"] = str(exc)
    if server is not None:
        info["server_port"] = getattr(server, "port", None)
        info["server_running"] = server.running() if hasattr(server, "running") else None
        info["server_command"] = getattr(server, "command", None)
    return info


def _classify_start_failure(
    error: Exception,
    server_diagnostics: Optional[dict[str, Any]] = None,
    directories: Optional[dict[str, dict[str, Any]]] = None,
) -> str:
    """Classify COMSOL startup failures into actionable buckets."""
    text = f"{type(error).__name__}: {error}".lower()
    server_started = bool(server_diagnostics and server_diagnostics.get("port"))
    if any(keyword in text for keyword in ("用户名", "密码", "password", "login", "authentication")):
        return "server_login_failed" if server_started else "login_or_credentials_failed"
    if "license" in text or "许可证" in text or "licence" in text:
        return "license_checkout_failed"
    if "permission" in text or "拒绝访问" in text or "access denied" in text or "not writable" in text:
        return "filesystem_or_process_permission_failed"
    if "port" in text and ("requested" in text or "refused" in text or "connect" in text):
        return "port_or_connection_failed"
    if isinstance(error, TimeoutError) or "timeout" in text or "time-out" in text:
        return "server_start_timeout"
    if server_started:
        return "server_started_client_connect_failed"
    if directories:
        user_blocked = any(
            key.startswith("user_") and value.get("exists") and not value.get("writable")
            for key, value in directories.items()
        )
        if user_blocked:
            return "user_profile_permissions_suspect"
    return "unknown_start_failure"


def build_startup_preflight(version: Optional[str] = None, create_runtime_dirs: bool = False) -> dict[str, Any]:
    """Build a structured COMSOL startup readiness report."""
    try:
        mph_options = mph.option().copy()
    except Exception as exc:
        mph_options = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "success": True,
        "runtimes": {
            "java": _runtime_path("COMSOL_JAVA_EXE", DEFAULT_COMSOL_JAVA_EXE),
            "javac": _runtime_path("COMSOL_JAVAC_EXE", DEFAULT_COMSOL_JAVAC_EXE),
            "comsolbatch": _runtime_path("COMSOL_BATCH_EXE", DEFAULT_COMSOL_BATCH_EXE),
            "comsolcompile": _runtime_path("COMSOL_COMPILE_EXE", DEFAULT_COMSOL_COMPILE_EXE),
            "comsolmphserver": _runtime_path("COMSOL_MPH_SERVER_EXE", DEFAULT_COMSOL_MPH_SERVER_EXE),
        },
        "python_packages": {
            "mph": _package_version("MPh"),
            "jpype": _package_version("JPype1"),
        },
        "mph_options": mph_options,
        "backend": _backend_report(version),
        "directories": _directory_report(create_runtime_dirs=create_runtime_dirs),
        "login_properties": _login_properties_report(),
        "ports": _port_report(),
        "processes": _process_report(),
        "cleanup_policy": (
            "Preflight is diagnostic only. Do not automatically kill unknown COMSOL "
            "or Java processes; only stop MCP-owned ManagedComsolServer instances."
        ),
    }


def _write_start_failure_report(
    error: Exception,
    *,
    version: Optional[str],
    cores: Optional[int],
    timeout_seconds: int,
    mode: str,
    port: Optional[int],
    redirect_user_dirs: bool,
    login_mode: str,
    failure_category: str,
    runtime_root: Path | None = None,
    server_diagnostics: Optional[dict[str, Any]] = None,
) -> Path:
    """Persist a startup failure report for post-mortem debugging."""
    DEV_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = DEV_LOG_DIR / f"comsol_start_timeout_{timestamp}.json"
    report = {
        "timestamp": timestamp,
        "error": f"{type(error).__name__}: {error}",
        "request": {
            "version": version,
            "cores": cores,
            "timeout_seconds": timeout_seconds,
            "mode": mode,
            "port": port,
            "redirect_user_dirs": redirect_user_dirs,
            "login_mode": login_mode,
        },
        "failure_category": failure_category,
        "server_arguments": _comsol_server_arguments(runtime_root) if redirect_user_dirs else [],
        "server_diagnostics": server_diagnostics or {},
        "login_properties": _login_properties_report(runtime_root),
        "preflight": build_startup_preflight(version=version, create_runtime_dirs=False),
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report_path


class SessionManager:
    """Singleton manager for COMSOL client session."""
    
    _instance: Optional["SessionManager"] = None
    _client: Optional[mph.Client] = None
    _server: Any = None
    _models: dict[str, mph.Model] = {}
    _current_model: Optional[str] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @property
    def client(self) -> Optional[mph.Client]:
        return self._client

    @property
    def server(self) -> Any:
        return self._server
    
    @property
    def is_connected(self) -> bool:
        return self._client is not None
    
    @property
    def current_model(self) -> Optional[str]:
        return self._current_model
    
    @property
    def models(self) -> dict[str, mph.Model]:
        return self._models.copy()
    
    def start(
        self,
        cores: Optional[int] = None,
        version: Optional[str] = None,
        timeout_seconds: int = DEFAULT_START_TIMEOUT_SECONDS,
        mode: str = DEFAULT_START_MODE,
        port: Optional[int] = DEFAULT_START_PORT,
        redirect_user_dirs: bool = True,
        login_mode: str = DEFAULT_LOGIN_MODE,
    ) -> dict:
        """Start a COMSOL client session."""
        if self._client is not None:
            try:
                self._client.clear()
                self._models.clear()
                self._current_model = None
                return {
                    "success": True,
                    **_safe_client_info(self._client, self._server),
                    "message": "Cleared existing session and ready."
                }
            except Exception as e:
                return {"success": False, "error": f"Failed to clear existing session: {e}"}
        if mode not in ("client-server", "stand-alone"):
            return {"success": False, "error": f"Unsupported COMSOL start mode: {mode}"}
        if login_mode not in ALLOWED_LOGIN_MODES:
            return {"success": False, "error": f"Unsupported COMSOL login mode: {login_mode}"}
        if timeout_seconds <= 0:
            return {"success": False, "error": "timeout_seconds must be greater than 0"}
        directories = _directory_report(create_runtime_dirs=redirect_user_dirs)
        if redirect_user_dirs:
            blocked = {
                key: value for key, value in directories.items()
                if key.startswith("runtime_") and not value.get("writable")
            }
            if blocked:
                return {
                    "success": False,
                    "error": "Redirected COMSOL runtime directories are not writable.",
                    "directories": blocked,
                }
        try:
            if mode == "client-server":
                arguments = _comsol_server_arguments() if redirect_user_dirs else []
                self._server = _start_local_comsol_server(
                    cores=cores,
                    version=version,
                    port=port,
                    timeout_seconds=timeout_seconds,
                    arguments=arguments,
                    login_mode=login_mode,
                )
                self._client = mph.Client(cores=cores, version=version, port=self._server.port)
            else:
                self._client = mph.Client(cores=cores, version=version)
            return {
                "success": True,
                **_safe_client_info(self._client, self._server),
                "mode": mode,
                "redirect_user_dirs": redirect_user_dirs,
                "runtime_root": str(DEFAULT_RUNTIME_ROOT) if redirect_user_dirs else None,
                "login_mode": login_mode,
            }
        except Exception as e:
            self._client = None
            server_diagnostics = {
                "command": getattr(e, "command", None),
                "last_output_lines": getattr(e, "output_lines", []),
            }
            if self._server is not None:
                server_diagnostics = {
                    "command": getattr(self._server, "command", None),
                    "port": getattr(self._server, "port", None),
                    "running_before_cleanup": self._server.running() if hasattr(self._server, "running") else None,
                    "last_output_lines": getattr(self._server, "output_lines", [])[-20:],
                }
                try:
                    if hasattr(self._server, "running") and self._server.running():
                        self._server.stop(timeout=5)
                except Exception:
                    pass
                self._server = None
            failure_category = _classify_start_failure(e, server_diagnostics, directories)
            report_path = _write_start_failure_report(
                e,
                version=version,
                cores=cores,
                timeout_seconds=timeout_seconds,
                mode=mode,
                port=port,
                redirect_user_dirs=redirect_user_dirs,
                login_mode=login_mode,
                failure_category=failure_category,
                server_diagnostics=server_diagnostics,
            )
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "failure_category": failure_category,
                "failure_report": str(report_path),
                "mode": mode,
                "login_mode": login_mode,
                "runtime_root": str(DEFAULT_RUNTIME_ROOT) if redirect_user_dirs else None,
                "server_diagnostics": server_diagnostics,
                "directories": directories,
                "login_properties": _login_properties_report(),
            }
    
    def connect(self, port: int, host: str = "localhost") -> dict:
        """Connect to a remote COMSOL server."""
        if self._client is not None:
            return {
                "success": False,
                "error": "COMSOL session already running. Disconnect first."
            }
        try:
            self._client = mph.Client(port=port, host=host)
            return {
                "success": True,
                **_safe_client_info(self._client, host=host),
                "port": port,
                "host": host,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "failure_category": _classify_start_failure(
                    e,
                    {"port": port, "host": host},
                    _directory_report(create_runtime_dirs=False),
                ),
                "login_properties": _login_properties_report(),
            }
    
    def disconnect(self) -> dict:
        """Disconnect and clear the session."""
        if self._client is None and self._server is None:
            return {"success": True, "message": "No active session."}
        messages = []
        if self._client is not None:
            try:
                self._client.clear()
            except Exception as exc:
                messages.append(f"client clear error: {exc}")
            if getattr(self._client, "port", None):
                try:
                    self._client.disconnect()
                except Exception as exc:
                    messages.append(f"client disconnect error: {exc}")
            self._client = None
        self._models.clear()
        self._current_model = None
        if self._server is not None:
            try:
                if not hasattr(self._server, "running") or self._server.running():
                    self._server.stop(timeout=10)
                messages.append("local COMSOL server stopped")
            except Exception as exc:
                messages.append(f"server stop error: {exc}")
            finally:
                self._server = None
        return {"success": True, "message": "; ".join(messages) or "Session cleared and disconnected."}
    
    def get_status(self) -> dict:
        """Get current session status."""
        if self._client is None:
            return {
                "connected": False,
                "message": "No active COMSOL session."
            }
        
        model_list = []
        for name in self._client.names():
            model_info = {"name": name}
            if name in self._models:
                model = self._models[name]
                model_info["file"] = model.file() if hasattr(model, 'file') else None
            model_list.append(model_info)
        
        return {
            "connected": True,
            **_safe_client_info(self._client, self._server),
            "models": model_list,
            "current_model": self._current_model,
        }
    
    def add_model(self, model: mph.Model) -> str:
        """Add a model to tracking."""
        name = model.name()
        self._models[name] = model
        if self._current_model is None:
            self._current_model = name
        return name
    
    def get_model(self, name: Optional[str] = None) -> Optional[mph.Model]:
        """Get a model by name or current model."""
        if name is None:
            name = self._current_model
        return self._models.get(name)
    
    def set_current_model(self, name: str) -> bool:
        """Set the current active model."""
        if name in self._models:
            self._current_model = name
            return True
        return False
    
    def remove_model(self, name: str) -> bool:
        """Remove a model from tracking and client."""
        if name in self._models and self._client is not None:
            try:
                self._client.remove(self._models[name])
                del self._models[name]
                if self._current_model == name:
                    self._current_model = next(iter(self._models.keys()), None)
                return True
            except Exception:
                pass
        return False


session_manager = SessionManager()


def register_session_tools(mcp: FastMCP) -> None:
    """Register session management tools with the MCP server."""
    
    @mcp.tool()
    def comsol_start(
        cores: Optional[int] = None,
        version: Optional[str] = None,
        timeout_seconds: int = DEFAULT_START_TIMEOUT_SECONDS,
        mode: str = DEFAULT_START_MODE,
        port: Optional[int] = DEFAULT_START_PORT,
        redirect_user_dirs: bool = True,
        login_mode: str = DEFAULT_LOGIN_MODE,
    ) -> dict:
        """
        Start a local COMSOL client session.
        
        Args:
            cores: Number of processor cores to use (default: all available)
            version: COMSOL version to use, e.g., '6.0' (default: latest installed)
            timeout_seconds: Maximum time to wait for local COMSOL server startup
            mode: Start mode, either 'client-server' or 'stand-alone'
            port: Port for client-server mode (0 asks COMSOL to pick a free port)
            redirect_user_dirs: Redirect COMSOL writable directories under the MCP repo
            login_mode: COMSOL server login mode: auto, never, force, or info
        
        Returns:
            Session info including version and core count, or error message
        """
        return session_manager.start(
            cores=cores,
            version=version,
            timeout_seconds=timeout_seconds,
            mode=mode,
            port=port,
            redirect_user_dirs=redirect_user_dirs,
            login_mode=login_mode,
        )
    
    @mcp.tool()
    def comsol_connect(port: int, host: str = "localhost") -> dict:
        """
        Connect to a remote COMSOL server.
        
        Args:
            port: Port number the COMSOL server is listening on
            host: Server hostname or IP address (default: 'localhost')
        
        Returns:
            Connection info or error message
        """
        return session_manager.connect(port=port, host=host)
    
    @mcp.tool()
    def comsol_disconnect() -> dict:
        """
        Disconnect from COMSOL and clear all models from memory.
        
        Returns:
            Success status and message
        """
        return session_manager.disconnect()
    
    @mcp.tool()
    def comsol_status() -> dict:
        """
        Get the current COMSOL session status.
        
        Returns:
            Session information including connection status, version, and loaded models
        """
        return session_manager.get_status()

    @mcp.tool()
    def comsol_startup_preflight(version: Optional[str] = None, create_runtime_dirs: bool = False) -> dict:
        """
        Diagnose local COMSOL startup readiness without starting COMSOL.

        Args:
            version: Optional COMSOL version to resolve through MPh discovery
            create_runtime_dirs: Create and probe redirected runtime directories

        Returns:
            Structured report of runtimes, package versions, backends, directories,
            default COMSOL ports, and related processes.
        """
        return build_startup_preflight(version=version, create_runtime_dirs=create_runtime_dirs)

    @mcp.tool()
    def comsol_java_runtime_status() -> dict:
        """
        Check configured COMSOL Java and launcher runtime executables.

        This is diagnostic only; MCP modeling still runs through the active
        Python/MPh/JPype COMSOL client session by default.

        Returns:
            Paths and existence checks for Java, javac, comsolbatch, and comsolcompile
        """
        runtimes = {
            "java": _runtime_path("COMSOL_JAVA_EXE", DEFAULT_COMSOL_JAVA_EXE),
            "javac": _runtime_path("COMSOL_JAVAC_EXE", DEFAULT_COMSOL_JAVAC_EXE),
            "comsolbatch": _runtime_path("COMSOL_BATCH_EXE", DEFAULT_COMSOL_BATCH_EXE),
            "comsolcompile": _runtime_path("COMSOL_COMPILE_EXE", DEFAULT_COMSOL_COMPILE_EXE),
        }
        return {
            "success": True,
            "runtimes": runtimes,
            "note": (
                "Bare java.exe does not automatically include COMSOL Model API "
                "classpath, native libraries, license, or current MCP model context."
            ),
        }
