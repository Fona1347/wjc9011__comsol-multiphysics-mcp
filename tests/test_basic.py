"""Basic tests for COMSOL MCP Server."""

import pytest


class TestVersioning:
    """Tests for version naming utilities."""
    
    def test_generate_version_name(self):
        from src.utils.versioning import generate_version_name
        
        result = generate_version_name("model.mph")
        assert result.startswith("model_")
        assert result.endswith(".mph")
        assert len(result) > len("model.mph")
    
    def test_generate_version_name_no_extension(self):
        from src.utils.versioning import generate_version_name
        
        result = generate_version_name("model")
        assert result.startswith("model_")
        assert result.endswith(".mph")
    
    def test_generate_version_path(self):
        from pathlib import Path

        from src.utils.versioning import generate_version_path
        
        result = generate_version_path("/path/to/model.mph")
        path = Path(result)
        assert path.parent.name == "model"
        assert path.parent.parent.name == "comsol_models"
        assert path.name.startswith("model_")
        assert path.suffix == ".mph"
    
    def test_parse_version_info_valid(self):
        from src.utils.versioning import parse_version_info
        
        result = parse_version_info("model_20260215_143022.mph")
        assert result is not None
        assert result["base_name"] == "model"
        assert result["timestamp"] == "20260215_143022"
    
    def test_parse_version_info_invalid(self):
        from src.utils.versioning import parse_version_info
        
        result = parse_version_info("model.mph")
        assert result is None
        
        result = parse_version_info("model_20260215.mph")
        assert result is None


class TestSessionManager:
    """Tests for session manager (without actual COMSOL)."""

    def reset_session_manager(self):
        from src.tools.session import SessionManager

        sm = SessionManager()
        sm._client = None
        sm._server = None
        sm._models.clear()
        sm._current_model = None
        sm._state = "disconnected"
        sm._connection_host = None
        sm._connection_port = None
        sm._last_error_code = None
        return sm
    
    def test_session_manager_singleton(self):
        from src.tools.session import SessionManager
        
        sm1 = SessionManager()
        sm2 = SessionManager()
        assert sm1 is sm2
    
    def test_session_manager_initial_state(self):
        sm = self.reset_session_manager()
        assert sm.client is None
        assert not sm.is_connected
        assert sm.current_model is None
        assert sm.models == {}
    
    def test_get_status_disconnected(self):
        sm = self.reset_session_manager()
        status = sm.get_status()
        assert status["connected"] is False

    def test_comsol_server_arguments_redirect_runtime_dirs(self, tmp_path):
        from src.tools.session import _comsol_server_arguments

        args = _comsol_server_arguments(tmp_path)
        assert args == [
            "-prefsdir",
            str(tmp_path / "prefs"),
            "-configuration",
            str(tmp_path / "configuration"),
            "-data",
            str(tmp_path / "data"),
            "-tmpdir",
            str(tmp_path / "tmp"),
            "-recoverydir",
            str(tmp_path / "recovery"),
        ]

    def test_check_directory_access_can_create_and_write(self, tmp_path):
        from src.tools.session import _check_directory_access

        report = _check_directory_access(tmp_path / "runtime" / "logs", create=True)
        assert report["exists"] is True
        assert report["is_dir"] is True
        assert report["created"] is True
        assert report["writable"] is True

    def test_login_properties_report_only_metadata(self, tmp_path):
        from src.tools.session import _login_properties_report

        login_file = tmp_path / "prefs" / "login.properties"
        login_file.parent.mkdir(parents=True)
        login_file.write_text("secret=do-not-report", encoding="utf-8")

        report = _login_properties_report(tmp_path)
        runtime_login = report["runtime_prefs_login"]
        assert runtime_login["exists"] is True
        assert runtime_login["size_bytes"] == len("secret=do-not-report")
        assert "secret" not in str(runtime_login)

    def test_connect_returns_without_client_metadata(self, monkeypatch):
        import src.tools.session as session

        calls = {}

        class DummyClient:
            version = "6.4"
            standalone = False
            port = 2037
            host = "localhost"

            @property
            def cores(self):
                calls["cores_accessed"] = True
                raise AssertionError("connect should not read client metadata")

        dummy_client = DummyClient()

        def client_factory(**kwargs):
            calls["client_kwargs"] = kwargs
            return dummy_client

        monkeypatch.setattr(session.mph, "Client", client_factory)
        monkeypatch.setattr(session, "_port_open", lambda host, port: True)
        sm = self.reset_session_manager()

        result = sm.connect(port=2037, host="localhost")

        assert result["success"] is True
        assert result["error_code"] is None
        assert result["session_state"] == "connected"
        assert result["current_model"] is None
        assert result["connected"] is True
        assert result["port"] == 2037
        assert result["host"] == "localhost"
        assert result["data"] == {"connected": True, "port": 2037, "host": "localhost"}
        assert calls["client_kwargs"] == {"port": 2037, "host": "localhost"}
        assert "cores_accessed" not in calls
        assert sm.client is dummy_client

    def test_connect_then_status_returns_client_metadata(self, monkeypatch):
        import src.tools.session as session

        class DummyClient:
            version = "6.4"
            standalone = False
            port = 2037
            host = "localhost"

            @property
            def cores(self):
                return 6

            def names(self):
                return []

        monkeypatch.setattr(session.mph, "Client", lambda **kwargs: DummyClient())
        monkeypatch.setattr(session, "_port_open", lambda host, port: True)
        sm = self.reset_session_manager()

        connect_result = sm.connect(port=2037, host="localhost")
        status = sm.get_status()

        assert connect_result["success"] is True
        assert status["connected"] is True
        assert status["session_state"] == "connected"
        assert status["version"] == "6.4"
        assert status["standalone"] is False
        assert status["port"] == 2037
        assert status["host"] == "localhost"
        assert status["cores"] == 6
        assert status["models"] == []

    def test_connect_same_server_is_idempotent(self, monkeypatch):
        import src.tools.session as session

        calls = {"count": 0}

        class DummyClient:
            version = "6.4"
            standalone = False
            port = 2037
            host = "localhost"

            def names(self):
                return []

        def client_factory(**kwargs):
            calls["count"] += 1
            return DummyClient()

        monkeypatch.setattr(session.mph, "Client", client_factory)
        monkeypatch.setattr(session, "_port_open", lambda host, port: True)
        sm = self.reset_session_manager()

        first = sm.connect(port=2037, host="localhost")
        second = sm.connect(port=2037, host="localhost")

        assert first["success"] is True
        assert second["success"] is True
        assert second["idempotent"] is True
        assert calls["count"] == 1

    def test_connect_different_server_returns_structured_error(self, monkeypatch):
        import src.tools.session as session

        class DummyClient:
            version = "6.4"
            standalone = False
            port = 2037
            host = "localhost"

            def names(self):
                return []

        monkeypatch.setattr(session.mph, "Client", lambda **kwargs: DummyClient())
        monkeypatch.setattr(session, "_port_open", lambda host, port: True)
        sm = self.reset_session_manager()

        assert sm.connect(port=2037, host="localhost")["success"] is True
        result = sm.connect(port=2036, host="localhost")

        assert result["success"] is False
        assert result["error_code"] == "already_connected_different_server"
        assert result["data"]["requested"] == {"host": "localhost", "port": 2036}
        assert result["data"]["active"] == {"host": "localhost", "port": 2037}

    def test_connect_closed_port_returns_structured_error(self, monkeypatch):
        import src.tools.session as session

        monkeypatch.setattr(session, "_port_open", lambda host, port: False)
        sm = self.reset_session_manager()

        result = sm.connect(port=2037, host="localhost")

        assert result["success"] is False
        assert result["error_code"] == "port_closed"
        assert result["session_state"] == "recoverable_error"

    def test_connect_mph_single_client_error_is_classified(self, monkeypatch):
        import src.tools.session as session

        monkeypatch.setattr(session, "_port_open", lambda host, port: True)
        monkeypatch.setattr(
            session.mph,
            "Client",
            lambda **kwargs: (_ for _ in ()).throw(
                NotImplementedError("Only one client can be instantiated per Python session")
            ),
        )
        sm = self.reset_session_manager()

        result = sm.connect(port=2037, host="localhost")

        assert result["success"] is False
        assert result["error_code"] == "mph_client_already_instantiated"

    def test_startup_preflight_recommends_preferred_open_port(self, monkeypatch):
        import src.tools.session as session

        monkeypatch.setattr(session, "_runtime_path", lambda env, default: {"exists": True, "path": str(default)})
        monkeypatch.setattr(session, "_package_version", lambda package: "test")
        monkeypatch.setattr(session, "_backend_report", lambda version=None: {"success": True})
        monkeypatch.setattr(session, "_directory_report", lambda create_runtime_dirs=False: {})
        monkeypatch.setattr(session, "_login_properties_report", lambda runtime_root=None: {})
        monkeypatch.setattr(session, "_process_report", lambda: [])
        monkeypatch.setattr(session.mph, "option", lambda: {})
        monkeypatch.setattr(session, "_port_open", lambda host, port, timeout=0.5: port == 2037)

        report = session.build_startup_preflight(version="6.4")

        assert report["preferred_connection"]["action"] == "connect"
        assert report["preferred_connection"]["port"] == 2037
        assert report["preferred_connection"]["preferred_ports"] == {2037: True, 2036: False}

    def test_start_uses_client_server_with_redirected_dirs(self, monkeypatch, tmp_path):
        import src.tools.session as session

        calls = {}

        class DummyServer:
            def __init__(self, **kwargs):
                calls["server"] = kwargs
                self.port = 45123

            def running(self):
                return True

            def stop(self, timeout=20):
                calls["stopped"] = timeout

        class DummyClient:
            version = "6.4"
            standalone = False
            port = 45123
            host = "localhost"

            @property
            def cores(self):
                return 2

            def clear(self):
                calls["cleared"] = True

            def disconnect(self):
                calls["disconnected"] = True

            def names(self):
                return []

        monkeypatch.setattr(session, "DEFAULT_RUNTIME_ROOT", tmp_path / "runtime")
        monkeypatch.setattr(
            session,
            "_start_local_comsol_server",
            lambda cores, version, port, timeout_seconds, arguments, login_mode="auto": DummyServer(
                cores=cores,
                version=version,
                port=port,
                timeout=timeout_seconds,
                arguments=arguments,
                login_mode=login_mode,
            ),
        )
        monkeypatch.setattr(session.mph, "Client", lambda **kwargs: DummyClient())
        sm = self.reset_session_manager()

        result = sm.start(cores=2, version="6.4", timeout_seconds=7)

        assert result["success"] is True
        assert result["version"] == "6.4"
        assert result["standalone"] is False
        assert result["server_port"] == 45123
        assert calls["server"]["cores"] == 2
        assert calls["server"]["version"] == "6.4"
        assert calls["server"]["timeout"] == 7
        assert calls["server"]["port"] == 0
        assert calls["server"]["login_mode"] == "auto"
        assert "-prefsdir" in calls["server"]["arguments"]
        assert calls["server"]["arguments"][1] == str(tmp_path / "runtime" / "prefs")

    def test_start_passes_login_mode(self, monkeypatch, tmp_path):
        import src.tools.session as session

        calls = {}

        class DummyServer:
            def __init__(self, **kwargs):
                calls["server"] = kwargs
                self.port = 45123

            def running(self):
                return True

        class DummyClient:
            version = "6.4"
            standalone = False
            port = 45123
            host = "localhost"

            @property
            def cores(self):
                return 2

            def names(self):
                return []

        monkeypatch.setattr(session, "DEFAULT_RUNTIME_ROOT", tmp_path / "runtime")
        monkeypatch.setattr(
            session,
            "_start_local_comsol_server",
            lambda cores, version, port, timeout_seconds, arguments, login_mode="auto": DummyServer(
                cores=cores,
                version=version,
                port=port,
                timeout=timeout_seconds,
                arguments=arguments,
                login_mode=login_mode,
            ),
        )
        monkeypatch.setattr(session.mph, "Client", lambda **kwargs: DummyClient())
        sm = self.reset_session_manager()

        result = sm.start(cores=2, version="6.4", login_mode="never")

        assert result["success"] is True
        assert result["login_mode"] == "never"
        assert calls["server"]["login_mode"] == "never"

    def test_start_rejects_invalid_login_mode(self):
        sm = self.reset_session_manager()

        result = sm.start(login_mode="invalid")

        assert result["success"] is False
        assert "Unsupported COMSOL login mode" in result["error"]

    def test_not_writable_error_is_permission_category(self):
        from src.tools.session import _classify_start_failure

        error = TimeoutError("configuration area is not writable")

        assert _classify_start_failure(error) == "filesystem_or_process_permission_failed"

    def test_start_timeout_writes_report_and_clears_state(self, monkeypatch, tmp_path):
        import src.tools.session as session

        class FailingServer:
            def __init__(self, **kwargs):
                raise TimeoutError("COMSOL did not report a port")

        monkeypatch.setattr(session, "DEFAULT_RUNTIME_ROOT", tmp_path / "runtime")
        monkeypatch.setattr(session, "DEV_LOG_DIR", tmp_path / "dev_log")
        monkeypatch.setattr(session, "build_startup_preflight", lambda **kwargs: {"success": True})
        monkeypatch.setattr(
            session,
            "_start_local_comsol_server",
            lambda cores, version, port, timeout_seconds, arguments, login_mode="auto": FailingServer(
                cores=cores,
                version=version,
                port=port,
                timeout=timeout_seconds,
                arguments=arguments,
                login_mode=login_mode,
            ),
        )
        sm = self.reset_session_manager()

        result = sm.start(cores=1, version="6.4", timeout_seconds=1)

        assert result["success"] is False
        assert "TimeoutError" in result["error"]
        assert sm.client is None
        assert sm.server is None
        report_path = result["failure_report"]
        assert report_path.endswith(".json")
        assert (tmp_path / "dev_log").exists()

    def test_client_login_failure_is_classified(self, monkeypatch, tmp_path):
        import src.tools.session as session

        class DummyServer:
            port = 45123
            command = ["comsolmphserver.exe", "-login", "auto"]
            output_lines = ["COMSOL Multiphysics server listening on port 45123"]

            def running(self):
                return True

            def stop(self, timeout=20):
                self.stopped = timeout

        def failing_client(**kwargs):
            raise RuntimeError("用户名或密码错误。")

        monkeypatch.setattr(session, "DEFAULT_RUNTIME_ROOT", tmp_path / "runtime")
        monkeypatch.setattr(session, "DEV_LOG_DIR", tmp_path / "dev_log")
        monkeypatch.setattr(session, "build_startup_preflight", lambda **kwargs: {"success": True})
        monkeypatch.setattr(
            session,
            "_start_local_comsol_server",
            lambda cores, version, port, timeout_seconds, arguments, login_mode="auto": DummyServer(),
        )
        monkeypatch.setattr(session.mph, "Client", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("wrong password")))
        sm = self.reset_session_manager()

        result = sm.start(version="6.4")

        assert result["success"] is False
        assert result["failure_category"] == "server_login_failed"
        assert result["login_mode"] == "auto"
        assert result["server_diagnostics"]["port"] == 45123
        assert sm.client is None
        assert sm.server is None


class TestToolRegistry:
    """Tests for MCP tool registry diagnostics."""

    def test_tool_registry_check_reports_core_tools(self):
        from mcp.server.fastmcp import FastMCP

        from src.tools.model import register_model_tools
        from src.tools.registry import build_tool_registry_report, register_registry_tools
        from src.tools.session import register_session_tools

        mcp = FastMCP("test")
        register_session_tools(mcp)
        register_model_tools(mcp)
        register_registry_tools(mcp)

        report = build_tool_registry_report(mcp)

        assert report["success"] is True
        assert report["missing_core_tools"] == []
        assert "tool_registry_check" in report["registered_tools"]
        assert "comsol_connect" in report["registered_tools"]
        assert "model_create" in report["registered_tools"]


class TestModelToolEnvelope:
    """Tests for model MCP tools with mocked COMSOL objects."""

    def reset_session_manager(self):
        from src.tools.session import SessionManager

        sm = SessionManager()
        sm._client = None
        sm._server = None
        sm._models.clear()
        sm._current_model = None
        sm._state = "disconnected"
        sm._connection_host = None
        sm._connection_port = None
        sm._last_error_code = None
        return sm

    @pytest.mark.asyncio
    async def test_model_create_list_inspect_return_envelope(self):
        from mcp.server.fastmcp import FastMCP

        from src.tools.model import register_model_tools

        class FakeModel:
            def __init__(self, name):
                self._name = name

            def name(self):
                return self._name

            def file(self):
                return None

            def version(self):
                return "6.4"

            def parameters(self):
                return {}

            def functions(self):
                return []

            def components(self):
                return []

            def geometries(self):
                return []

            def selections(self):
                return []

            def physics(self):
                return []

            def multiphysics(self):
                return []

            def materials(self):
                return []

            def meshes(self):
                return []

            def studies(self):
                return []

            def solutions(self):
                return []

            def datasets(self):
                return []

            def plots(self):
                return []

            def exports(self):
                return []

            def modules(self):
                return []

            def problems(self):
                return []

        class FakeClient:
            def create(self, name=None):
                return FakeModel(name or "Model")

        sm = self.reset_session_manager()
        sm._client = FakeClient()
        sm._state = "connected"

        mcp = FastMCP("test")
        register_model_tools(mcp)

        create = await mcp._tool_manager.get_tool("model_create").run({"name": "smoke"})
        listed = await mcp._tool_manager.get_tool("model_list").run({})
        inspected = await mcp._tool_manager.get_tool("model_inspect").run({})

        assert create["success"] is True
        assert create["error_code"] is None
        assert create["session_state"] == "model_active"
        assert create["model"] == {"name": "smoke", "is_new": True}
        assert listed["success"] is True
        assert listed["models"][0]["name"] == "smoke"
        assert inspected["success"] is True
        assert inspected["model"]["name"] == "smoke"

    @pytest.mark.asyncio
    async def test_model_create_without_session_returns_no_active_session(self):
        from mcp.server.fastmcp import FastMCP

        from src.tools.model import register_model_tools

        self.reset_session_manager()
        mcp = FastMCP("test")
        register_model_tools(mcp)

        result = await mcp._tool_manager.get_tool("model_create").run({"name": "smoke"})

        assert result["success"] is False
        assert result["error_code"] == "no_active_session"
        assert result["session_state"] == "recoverable_error"
