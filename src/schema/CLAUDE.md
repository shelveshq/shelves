# Schema — CLAUDE.md

This module handles **Parse**: YAML string → `ChartSpec` via Pydantic.

## Files

- `chart_schema.py` — Full DSL grammar: `ChartSpec`, shelf models, filter operators, mark types, all Pydantic validators
- `field_types.py` — `FieldTypeResolver` protocol + `DataBlockResolver`: resolves field names to Vega-Lite types (quantitative/temporal/nominal) from the `data` block

## Key Rules

- **DSL versioning:** `DSL_VERSION` lives in `chart_schema.py` (currently `0.1.0`). Bump on grammar changes (semver: major = breaking, minor = additive, patch = fixes). `ChartSpec` accepts an optional `version` field.
- **Validation constraint:** At most ONE of `rows`/`cols` can be a multi-measure list; single-measure charts require top-level `marks`.
- **Inheritance:** Top-level `marks`/`color`/`detail` cascade down to multi-measure entries → layer entries. More specific overrides less specific.
- **FieldTypeResolver protocol:** An abstraction that allows pluggable type resolution (e.g., from data block, from semantic layer models). The translator depends on this protocol, not the concrete implementation.

## Documentation Requirement

**Any change to the DSL (`chart_schema.py`) MUST be accompanied by updates to:**
- `docs/guide/dsl-reference.md` — update relevant field/property docs, examples, and type tables
- `docs/guide/getting-started.md` — update if the change affects introductory workflow or basic examples

This applies to: new fields, removed fields, changed types, new operators, new mark types, new filter operators, renamed properties, or any change to validation rules.
