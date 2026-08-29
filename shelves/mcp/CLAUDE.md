# MCP — CLAUDE.md

The **agent-facing** surface: an MCP (Model Context Protocol) server that lets a
coding agent discover a semantic model and author chart/dashboard YAML against
it. Thin protocol adapters over the existing public API — no new pipeline logic
lives here. Governing spec: `docs/foundational/MCP Specification.md`.

## Files

- `tools.py` — Pure tool implementations. No MCP protocol types in their
  signatures, so they are unit-testable and `server.py` stays a thin
  registration layer. Each returns a JSON-serializable dict/list. Errors are
  **returned**, never raised across the boundary, as
  `{"error": {"code", "message", "did_you_mean"?, "valid_options"?, "fix_hint"?}}`
  using the `shelves.validation.ValidationErrorItem` vocabulary. Holds
  `MCPContext` (`project_dir` + `models_dir`).
- `server.py` — Registration layer. `build_server(ctx)` binds each tool to an
  `MCPContext` so agent-facing signatures expose only domain arguments
  (`model`, `field`, `kind`, …), never `project_dir`/`models_dir`. Registers
  the resources. Tool/resource **docstrings are the descriptions the agent
  reads** — write them for agents.
- `cli.py` — `shelves-mcp` entry point; runs the stdio server. The `mcp` SDK is
  imported lazily so a core install imports fine; a missing SDK becomes a clear
  `pip install "shelves-bi[mcp]"` hint.
- `grammar.py` — Reader + token budget for the grammar card (`grammar_card()`,
  `estimate_tokens()`, `GRAMMAR_TOKEN_BUDGET`).
- `resources/grammar.md` — The grammar card (see below).
- `__init__.py` — Module docstring; `shelves.mcp.tools` is always importable,
  `shelves.mcp.server` only with the `mcp` extra.

## Tools (discovery → author → inspect)

`list_models` · `get_model` · `sample_field_values` · `list_parameters` ·
`list_specs` — discovery. `validate_spec` · `compile_chart` · `render_chart`
(PNG/HTML) · `render_dashboard` · `query_model` — authoring/inspection. Each
adapts an existing public API (model loader/resolver, domain resolver,
parameters loader, pipeline); no SQL and no per-backend branching here.

## Resources

- `shelves://schema/chart`, `shelves://schema/dashboard` — the generated JSON
  Schema (routed through `shelves.schema.json_schema`; see `shelves/schema/`).
- `shelves://grammar` — the grammar card.

## Grammar card

`resources/grammar.md` is the **whole DSL on one page**, written for LLM context
injection — canonical forms only plus one minimal example per shipped pattern,
a different genre from `docs/guide/dsl-reference.md` (no explanatory prose).
Load it plus a `get_model` menu before writing a spec. Contract: `LLM
Writability Specification.md` §3.1.

Guarded by `tests/test_grammar_card.py`, independent of wording:
- **Hard ≤ 2,500-token budget** (`estimate_tokens` = `ceil(len/4)`, no tiktoken
  dependency) — the CI gate. Keep examples terse.
- **Snippet smoke test** — every ` ```yaml ` block must **compile** through the
  pipeline against the `orders` fixture model (compile subsumes validate, so a
  spec that passes schema/model checks but breaks the translator is caught).
  `$param` refs compile because the test threads the fixture `ParameterSet`
  (defaults, `resolve_domains=False`). Non-compilable fragments use a ` ```text `
  fence and are excluded.
- **Mark coverage** — every `MarkType` value must appear in the "Marks (closed
  set)" list (scoped to that section, not incidental prose).

## Parameters

`compile_chart`, `render_chart`, and `render_dashboard` resolve `$parameter`
references via `_build_parameters` → `load_parameter_set` (the one entry point
every surface shares, so the MCP resolves identically to the CLIs). All three
accept a `params` override dict (stringified into the CLI override format,
`None` → the null token).

Domain resolution (the backend query that validates an override against a real
field domain) is gated:
- `compile_chart` always uses `resolve_domains=False` — it is the no-data
  inspection path, so a field-backed `$ref` never triggers a query. Overrides
  are still type/enum/range-checked; only the live field-domain check is
  deferred to render.
- the render paths use `resolve_domains=bool(params)` — a query only when there
  is an override to check. Without overrides they skip it, so a chart that uses
  no parameters keeps its purpose-built `data_unavailable` error instead of a
  domain-resolution `invalid_parameters`, even in a project that merely declares
  a field-backed parameter.

A missing/invalid parameters.yaml or a bad override becomes an
`invalid_parameters` structured error, never a raised exception. A sheet's
undeclared `$ref` inside a dashboard is wrapped by compose as a
`RuntimeError`-from-`ParameterReferenceError`; `render_dashboard` classifies it
`invalid_parameters` (via `__cause__`), matching the chart tools, while keeping
compose's "which sheet" context in the message.

## Key Rules

- **Any DSL change touches the card.** New field/enum/mark/operator → update
  `resources/grammar.md` within budget. This is on the `shelves/schema/CLAUDE.md`
  documentation checklist; the token/validate/coverage tests enforce it.
- **Docstrings are UI.** Tool and resource docstrings are what the agent sees —
  keep them agent-directed and current.
- **Thin wrapper.** Add logic to the pipeline/validation modules, not here; a
  tool that needs new behavior is a signal the public API is missing something.
- **Errors returned, not raised** — preserve the structured error shape.
