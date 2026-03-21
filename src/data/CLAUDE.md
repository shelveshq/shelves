# Data — CLAUDE.md

This module handles **data binding** — attaching data to translated Vega-Lite specs.

## Files

- `bind.py` — `bind_data(spec, rows)`: inline JSON rows (Phase 1, tests, offline use)
- `cube_client.py` — Cube REST API client: query builder, filter translation, response transformer. Also provides `resolve_data(spec, chart_spec)` for fetching from Cube.dev when no rows are provided.

## Key Design Decisions

- **Two modes:** Inline data binding (`bind_data`) vs. Cube.dev fetching (`resolve_data`). The CLI/dev server picks the right one based on whether `--data` is provided.
- **Cube prefix stripping:** Cube returns keys like `orders.field_name` — `cube_client.py` strips to just `field_name` to match DSL conventions.
- **Filter push-down:** DSL `ShelfFilter` operators are translated to Cube filter format and pushed to the API, not filtered client-side.
- **Environment:** Cube integration requires `CUBE_API_URL` and `CUBE_API_TOKEN` env vars.
