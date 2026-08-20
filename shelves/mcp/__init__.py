"""
Shelves MCP server — the agent-facing interface to the pipeline (SHE-55).

Thin protocol adapters over the existing public API: discovery tools
(`list_models`, `get_model`, `sample_field_values`, `list_parameters`,
`list_specs`) that let any coding agent discover a semantic model before it
writes a spec. No file I/O tools, no raw SQL, stateless — see
`docs/foundational/MCP Specification.md`.

The `mcp` SDK is an optional dependency; import `shelves.mcp.server` only when
it is installed (the `mcp` extra). `shelves.mcp.tools` is always importable.
"""
