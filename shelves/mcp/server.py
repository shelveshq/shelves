"""
MCP server assembly (SHE-55).

Registers the discovery tools from `tools.py` on an `MCPServer`, binding each to
an `MCPContext` so the agent-facing signatures expose only domain arguments
(`model`, `field`, `limit`, `kind`) — never `project_dir`/`models_dir`. Tool
docstrings become the descriptions the agent reads, so they are written for
agents.

The `mcp` SDK is an optional dependency (the `mcp` extra); it is imported inside
`build_server` so importing this module never fails on a core install — `cli.py`
turns a missing SDK into a clear install hint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from shelves.mcp import tools
from shelves.mcp.tools import MCPContext
from shelves.schema.chart_schema import DSL_VERSION

if TYPE_CHECKING:
    from mcp.server import MCPServer


def build_server(ctx: MCPContext) -> MCPServer:
    """Assemble the stdio MCP server with the discovery tools bound to `ctx`."""
    from mcp.server import MCPServer

    server: MCPServer = MCPServer(
        name="shelves",
        version=DSL_VERSION,
        instructions=(
            "Discover a Shelves semantic model, then write chart/dashboard YAML "
            "against it. Call get_model first for the metric menu; "
            "sample_field_values for the values a filter can use; "
            "list_parameters for runtime knobs; list_specs to extend existing specs."
        ),
    )

    @server.tool()
    def list_models() -> list[dict]:
        """List available semantic models (name, label, backend). Start here to
        see what data is available."""
        return tools.list_models(ctx)

    @server.tool()
    def get_model(model: str) -> dict:
        """The metric menu for one model: measures and dimensions with types,
        formats, and temporal grains. Call this FIRST before writing a spec."""
        return tools.get_model(ctx, model)

    @server.tool()
    def sample_field_values(model: str, field: str, limit: int = 20) -> dict:
        """Distinct values of a nominal dimension, or (min, max) bounds of a
        temporal/numeric one. Use before writing a filter to see valid values."""
        return tools.sample_field_values(ctx, model, field, limit)

    @server.tool()
    def list_parameters() -> dict:
        """Declared runtime parameters (the knobs a chart can be re-rendered
        with): name, type, default, and whether values come from a model field."""
        return tools.list_parameters(ctx)

    @server.tool()
    def list_specs(kind: str | None = None) -> dict:
        """Inventory of chart and dashboard YAMLs already in the project, so you
        extend rather than duplicate. Optional kind = "chart" or "dashboard"."""
        return tools.list_specs(ctx, kind)

    return server


def serve(ctx: MCPContext, **run_kwargs: Any) -> None:
    """Build and run the server over stdio (blocking)."""
    build_server(ctx).run(transport="stdio", **run_kwargs)
