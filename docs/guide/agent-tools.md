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
server never writes *spec* files (your agent already has file tools; only the
render tools below write rendered PNG/HTML into `output/`). Results report the
DSL schema version so an agent knows which grammar it is writing.

## Authoring tools

The correction loop — write → validate → fix → render → look:

| Tool | What it does |
| --- | --- |
| `validate_spec` | Validate chart/dashboard YAML against schema **and** the semantic model. Returns every error at once — line numbers, valid options, did-you-mean suggestions — or the normalized canonical spec. |
| `compile_chart` | The compiled, theme-merged Vega-Lite for one chart (no data), for inspecting how the DSL translates. |
| `render_chart` | Render a chart to **PNG** (default — a multimodal agent can look at it to catch schema-valid-but-wrong charts) or HTML. |
| `render_dashboard` | Render a dashboard (layout tree of sheets) to HTML. |
| `query_model` | Run an aggregated query through the semantic layer to sanity-check data — same adapter a chart uses, no raw SQL. |

Every tool accepts inline `yaml_text` or a project `path`. Paths must stay
inside the project root.

### PNG limitations

`render_chart` produces PNG through vl-convert, with no browser. Data labels
(`label:`) and container-fit sizing for compound charts (facets, concatenations)
are browser features and do **not** appear in PNGs — the payload lists them
under `limitations`. Use `render_chart(..., format="html")` for full fidelity.
Dashboards are HTML-only for the same reason (their sizing is browser-computed).

Read-only resources (the grammar card, JSON Schema) land in a follow-up release.
