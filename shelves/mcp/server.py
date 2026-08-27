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

import base64
from typing import TYPE_CHECKING, Any

from shelves.mcp import tools
from shelves.mcp.grammar import grammar_card
from shelves.mcp.tools import MCPContext
from shelves.schema.chart_schema import DSL_VERSION
from shelves.schema.json_schema import chart_json_schema, dashboard_json_schema, dumps

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
            "against it. Read the shelves://grammar resource for the whole DSL on "
            "one page. Call get_model first for the metric menu; "
            "sample_field_values for the values a filter can use; "
            "list_parameters for runtime knobs; list_specs to extend existing specs. "
            "shelves://schema/{chart,dashboard} give the JSON Schema."
        ),
    )

    @server.tool()
    def list_models() -> dict:
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

    @server.tool()
    def validate_spec(
        yaml_text: str | None = None, path: str | None = None, kind: str | None = None
    ) -> dict:
        """Validate chart/dashboard YAML against schema AND the semantic model.
        Returns every error at once (line numbers, valid options, did-you-mean),
        or the normalized canonical spec. Pass yaml_text or a project path."""
        return tools.validate_spec(ctx, yaml_text=yaml_text, path=path, kind=kind)

    @server.tool()
    def compile_chart(
        yaml_text: str | None = None,
        path: str | None = None,
        theme: str | None = None,
        params: dict | None = None,
    ) -> dict:
        """The compiled, theme-merged Vega-Lite for one chart (no data), for
        inspecting how the DSL translates. `$parameter` references resolve to
        their declared defaults; pass `params` (e.g. {"metric": "cost"}) to
        preview under specific values. Invalid specs return validation errors."""
        return tools.compile_chart(ctx, yaml_text=yaml_text, path=path, theme=theme, params=params)

    @server.tool(structured_output=False)
    def render_chart(
        yaml_text: str | None = None,
        path: str | None = None,
        format: str = "png",
        params: dict | None = None,
    ) -> Any:
        """Render a chart to PNG (default — look at it to catch schema-valid but
        semantically-wrong charts) or HTML. PNG is headless: data labels and
        compound-chart fit are browser-only (reported in `limitations`).
        `$parameters` resolve to their defaults; override with `params`
        (e.g. {"metric": "cost"}) — values are checked against the model."""
        payload = tools.render_chart(
            ctx, yaml_text=yaml_text, path=path, format=format, params=params
        )
        png_base64 = payload.pop("png_base64", None)
        if png_base64 is None:
            return payload

        from mcp.server.mcpserver import Image

        image = Image(data=base64.b64decode(png_base64), format="png").to_image_content()
        return [image, payload]

    @server.tool()
    def render_dashboard(path: str, format: str = "html", params: dict | None = None) -> dict:
        """Render a dashboard (layout tree of sheets) to HTML via the compose
        pipeline. PNG is unsupported — dashboard sizing is browser-computed.
        `$parameters` resolve to their defaults; override with `params`."""
        return tools.render_dashboard(ctx, path, format=format, params=params)

    @server.tool()
    def query_model(
        model: str,
        measures: list[str],
        dimensions: list[str] | None = None,
        filters: list[dict] | None = None,
        limit: int = 500,
    ) -> dict:
        """Run an aggregated query through the semantic layer (sanity-check data
        before/after charting). Read-only and SQL-free — same adapter a chart uses."""
        return tools.query_model(
            ctx, model, measures, dimensions=dimensions, filters=filters, limit=limit
        )

    @server.resource(
        "shelves://schema/chart",
        name="Chart JSON Schema",
        mime_type="application/json",
    )
    def chart_schema_resource() -> str:
        """JSON Schema for a chart spec — for structured decoding and editor
        validation. A superset acceptor: cross-key validators are not encoded."""
        return dumps(chart_json_schema())

    @server.resource(
        "shelves://schema/dashboard",
        name="Dashboard JSON Schema",
        mime_type="application/json",
    )
    def dashboard_schema_resource() -> str:
        """JSON Schema for a dashboard spec — for structured decoding and editor
        validation. A superset acceptor: cross-key validators are not encoded."""
        return dumps(dashboard_json_schema())

    @server.resource(
        "shelves://grammar",
        name="Shelves Grammar Card",
        mime_type="text/markdown",
    )
    def grammar_resource() -> str:
        """The complete Shelves DSL on one page, written for context injection.
        Load this plus a get_model menu before writing chart/dashboard YAML."""
        return grammar_card()

    return server


def serve(ctx: MCPContext, **run_kwargs: Any) -> None:
    """Build and run the server over stdio (blocking)."""
    build_server(ctx).run(transport="stdio", **run_kwargs)
