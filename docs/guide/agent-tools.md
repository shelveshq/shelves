# Agent Tools (MCP)

Shelves ships an [MCP](https://modelcontextprotocol.io) server so coding agents
(Claude Code, Codex, Cursor) can discover your semantic model and build charts
against it — the same pipeline the CLIs use, exposed as tools.

## Setup

```bash
pip install "shelves-bi[mcp]"
shelves-mcp            # stdio server, run from your project root
```

Register in Claude Code:

```bash
claude mcp add shelves -- shelves-mcp
```

`shelves-mcp` resolves models from `<project>/models/` by default; override with
`--project-dir` and `--models-dir`. (Automatic project setup via `.mcp.json`
lands in a later release.)

## Discovery tools

| Tool | What it does |
| --- | --- |
| `list_models` | Available semantic models in `models/` (name, label, backend). |
| `get_model` | The field menu for one model — measures and dimensions with types, formats, and temporal grains. **Agents call this first.** |
| `sample_field_values` | Distinct values of a nominal dimension, or `(min, max)` bounds of a temporal/numeric one — for writing filters. |
| `list_parameters` | Declared runtime parameters (the knobs a chart can be re-rendered with). |
| `list_specs` | Chart and dashboard YAMLs already in the project, so agents extend rather than duplicate. |

Every tool goes through the semantic layer — there is no raw-SQL tool, and the
server never writes files (your agent already has file tools). Results report
the DSL schema version so an agent knows which grammar it is writing.

The authoring loop (`validate_spec`, `render_chart`, `compile_chart`,
`query_model`) and read-only resources (the grammar card, JSON Schema) land in
follow-up releases.
