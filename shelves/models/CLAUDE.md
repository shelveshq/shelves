# Models — CLAUDE.md

This module handles the **data model manifest** — defining reusable semantic models that map field names to data sources and types.

## Files

- `schema.py` — Pydantic models for the manifest format (model definitions, dimensions, measures)
- `loader.py` — Loads and parses model YAML files
- `resolver.py` — `ModelResolver`: implements the `FieldTypeResolver` protocol, resolving field types from model definitions instead of inline `data` blocks

## How It Connects

- Models provide an alternative to inline `data.fields` for type resolution
- The `ModelResolver` plugs into the same `FieldTypeResolver` protocol the translator uses
- When a chart references a `model` in its `data` block, the resolver looks up field types from the model manifest rather than the chart's own field declarations
- Dot notation is a **temporal grain suffix** (`order_date.month`), NOT model qualification. `ModelResolver._parse_field_ref` splits on the first dot and validates that the base field is a temporal dimension — using a dot on a measure or nominal dimension raises. There is no `model.field` syntax; a chart's model is set once by `data:`, and `parameters.yaml` names its model explicitly with separate `model:` and `field:` keys
