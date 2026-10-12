"""COMSOL MCP Server - Main entry point."""

import logging
import os
from mcp.server.fastmcp import FastMCP
from .tools.session import register_session_tools
from .tools.model import register_model_tools
from .tools.parameters import register_parameter_tools
from .tools.geometry import register_geometry_tools
from .tools.physics import register_physics_tools
from .tools.mesh import register_mesh_tools
from .tools.study import register_study_tools
from .tools.results import register_results_tools
from .tools.registry import build_tool_registry_report, register_registry_tools
from .resources.model_resources import register_model_resources
from .knowledge.embedded import register_knowledge_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROFILE_ENV = "HY_COMSOL_MCP_PROFILE"
CODEX_PROFILE = "codex"

mcp = FastMCP("COMSOL MCP")


def _active_profile() -> str:
    """Return the active MCP profile name."""
    return os.getenv(PROFILE_ENV, "").strip().lower()


def register_foundation_tools(target_mcp: FastMCP) -> None:
    """Register the small foundation toolset used by Codex-safe startup."""
    register_session_tools(target_mcp)
    register_model_tools(target_mcp)
    register_parameter_tools(target_mcp)


def register_modeling_tools(target_mcp: FastMCP) -> None:
    """Register higher-level modeling, results, and knowledge tools."""
    register_geometry_tools(target_mcp)
    register_physics_tools(target_mcp)
    register_mesh_tools(target_mcp)
    register_study_tools(target_mcp)
    register_results_tools(target_mcp)
    register_knowledge_tools(target_mcp)


def register_tools_for_profile(target_mcp: FastMCP, profile: str | None = None) -> dict:
    """Register tools for a named runtime profile and return a registry report."""
    selected_profile = (profile or "").strip().lower()
    register_foundation_tools(target_mcp)
    if selected_profile != CODEX_PROFILE:
        register_modeling_tools(target_mcp)
    register_registry_tools(target_mcp)
    return build_tool_registry_report(target_mcp)


def register_all_tools() -> None:
    """Register all MCP tools for the active profile."""
    profile = _active_profile()
    registry_report = register_tools_for_profile(mcp, profile)
    profile_label = profile or "default"
    skipped = " modeling tools skipped for Codex-safe profile;" if profile == CODEX_PROFILE else ""
    logger.info(
        "Registered %s tools;%s profile=%s; missing core tools: %s",
        registry_report["registered_count"],
        skipped,
        profile_label,
        registry_report["missing_core_tools"],
    )


def register_all_resources() -> None:
    """Register all MCP resources."""
    if _active_profile() == CODEX_PROFILE:
        logger.info("Skipped resources for Codex-safe profile")
        return
    register_model_resources(mcp)
    logger.info("Registered all resources")


def main() -> None:
    """Run the MCP server."""
    logger.info("Starting COMSOL MCP Server...")
    register_all_tools()
    register_all_resources()
    mcp.run()


if __name__ == "__main__":
    main()
