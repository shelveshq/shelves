# Schema — CLAUDE.md

This module handles **Parse**: YAML string → `ChartSpec` via Pydantic.

## Files

- `chart_schema.py` — Full chart DSL grammar: `ChartSpec`, shelf models, filter operators, mark types, label/axis/KPI config, all Pydantic validators
- `layout_schema.py` — Dashboard DSL grammar: `DashboardSpec`, component models, `parse_dashboard`/`load_dashboard`
- `field_types.py` — `FieldTypeResolver` protocol: resolve field names to Vega-Lite types (quantitative/temporal/nominal). The concrete implementation lives in `shelves/models/resolver.py`
- `temporal.py` — Time-grain helpers shared across schema and translator

## Key Rules

- **DSL versioning:** `DSL_VERSION` lives in `chart_schema.py` and covers the **whole** DSL — chart grammar *and* layout grammar. Bump on any grammar change (semver: major = breaking, minor = additive, patch = fixes) and add the row to the version table in `docs/guide/dsl-reference.md`. `ChartSpec` accepts an optional `version` field.
- **Validation constraint:** At most ONE of `rows`/`cols` can be a multi-measure list; single-measure charts require top-level `marks`.
- **Inheritance:** Top-level `marks`/`color`/`detail` cascade down to multi-measure entries → layer entries. More specific overrides less specific.
- **FieldTypeResolver protocol:** An abstraction that allows pluggable type resolution (e.g., from data block, from semantic layer models). The translator depends on this protocol, not on any specific resolver implementation.

## Generated JSON Schema

`json_schema.py` exports `ChartSpec` / `DashboardSpec` as JSON Schema, served as
the MCP resources `shelves://schema/{chart,dashboard}` and written to committed
artifacts bundled in the package at `shelves/schema/generated/` (shipped via
package-data). **Any grammar change must regenerate them** with `python -m
shelves.schema` — a test (`tests/test_json_schema_export.py`) diffs the committed
files against freshly generated output and fails on drift. Studio's `GET /schema`
and the MCP resources both route through `chart_json_schema()` — keep it the one
generation site. The schema is a one-directional superset acceptor: cross-key
`model_validator` rules are not expressible in JSON Schema, so never try to
encode them there. `DashboardSpec.root` is annotated `RootComponent` so the root
shape is validated; the `contains` subtree is `Any` on purpose.

## Documentation Requirement

**Any change to the DSL (`chart_schema.py`) MUST be accompanied by updates to:**
- `docs/guide/dsl-reference.md` — update relevant field/property docs, examples, and type tables
- `docs/guide/getting-started.md` — update if the change affects introductory workflow or basic examples
- `shelves/mcp/resources/grammar.md` — the grammar card (`shelves://grammar`), the whole DSL on one page for LLM context injection. Add the new canonical form / enum value / mark and keep it **within the ≤2,500-token budget** (CI-checked by `tests/test_grammar_card.py`). This is a different genre from `dsl-reference.md`: canonical forms only, no explanatory prose. See `LLM Writability Specification.md` §3.1.

This applies to: new fields, removed fields, changed types, new operators, new mark types, new filter operators, renamed properties, or any change to validation rules.
