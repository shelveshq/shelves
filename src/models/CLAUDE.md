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
- Dot notation (`model.field`) is supported for field references
