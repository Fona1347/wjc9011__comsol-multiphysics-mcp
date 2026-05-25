"""Tool registry diagnostics for the COMSOL MCP Server."""

from typing import Any

from mcp.server.fastmcp import FastMCP


CORE_TOOLS = (
    "comsol_status",
    "comsol_startup_preflight",
    "comsol_connect",
    "comsol_disconnect",
    "model_create",
    "model_list",
    "model_inspect",
    "model_create_component",
    "model_save",
)

OPTIONAL_TOOL_PREFIXES = (
    "param_",
    "geometry_",
    "material_",
    "physics_",
    "mesh_",
    "study_",
    "results_",
    "result_",
    "pdf_",
    "modeling_",
    "java_",
)


def get_registered_tool_names(mcp: FastMCP) -> list[str]:
    """Return registered FastMCP tool names using the stable manager shape."""
    tool_manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(tool_manager, "_tools", {}) if tool_manager is not None else {}
    if isinstance(tools, dict):
        return sorted(str(name) for name in tools.keys())
    return []


def build_tool_registry_report(mcp: FastMCP) -> dict[str, Any]:
    """Build a registry self-check report for startup logs and MCP calls."""
    registered = get_registered_tool_names(mcp)
    registered_set = set(registered)
    core_missing = [name for name in CORE_TOOLS if name not in registered_set]
    optional_registered = [
        name for name in registered
        if name not in CORE_TOOLS and any(name.startswith(prefix) for prefix in OPTIONAL_TOOL_PREFIXES)
    ]
    return {
        "success": len(core_missing) == 0,
        "error_code": None if len(core_missing) == 0 else "missing_core_tools",
        "message": (
            "Core HY-COMSOL-MCP tools are registered."
            if len(core_missing) == 0
            else "Some core HY-COMSOL-MCP tools are missing."
        ),
        "session_state": None,
        "current_model": None,
        "data": {
            "registered_tools": registered,
            "registered_count": len(registered),
            "core_tools": list(CORE_TOOLS),
            "missing_core_tools": core_missing,
            "optional_modeling_tools": optional_registered,
            "optional_modeling_count": len(optional_registered),
        },
        "artifacts": {},
        "registered_tools": registered,
        "registered_count": len(registered),
        "core_tools": list(CORE_TOOLS),
        "missing_core_tools": core_missing,
        "optional_modeling_tools": optional_registered,
    }


def register_registry_tools(mcp: FastMCP) -> None:
    """Register MCP registry diagnostics."""

    @mcp.tool()
    def tool_registry_check() -> dict:
        """
        Check which HY-COMSOL-MCP tools are registered in this MCP server.

        Returns:
            Core tool checklist, missing tools, and optional modeling tool summary.
        """
        return build_tool_registry_report(mcp)
