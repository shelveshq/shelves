# Data — CLAUDE.md

This module handles **data binding** — attaching data to translated Vega-Lite specs.

## Files

- `bind.py` — `bind_data(spec, rows)`: inline JSON rows (Phase 1, tests, offline use), plus `resolve_data(spec, chart_spec)`: top-level entry point that chooses between inline binding and Cube.dev fetching.
- `cube_client.py` — Cube REST API client: query builder, filter translation, response transformer. Exports `fetch_from_cube_model(...)` used by `resolve_data` when rows are not provided and data must be fetched from Cube.dev.

## Key Design Decisions

- **Two modes:** Inline data binding (`bind_data`) vs. Cube.dev fetching (`fetch_from_cube_model` via `resolve_data`). The CLI/dev server calls `resolve_data`, which picks the right one based on whether `--data` / rows are provided.
- **Cube prefix stripping:** Cube returns keys like `orders.field_name` — `cube_client.py` strips to just `field_name` to match DSL conventions.
- **Filter push-down:** DSL `ShelfFilter` operators are translated to Cube filter format and pushed to the API, not filtered client-side.
- **Environment:** Cube integration requires `CUBE_API_URL` and `CUBE_API_TOKEN` env vars.
