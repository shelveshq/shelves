# Data — CLAUDE.md

This module handles **data binding** — attaching data to translated Vega-Lite specs.

## Files

- `fields.py` — `collect_chart_fields(spec)`: walks a `ChartSpec` to extract every referenced field name. Pure domain logic, no data-source dependency. Used by both the Cube query builder and the future DuckDB adapter.
- `bind.py` — `bind_data(spec, rows)`: inline JSON rows (Phase 1, tests, offline use), plus `resolve_data(spec, chart_spec)`: top-level entry point that chooses between inline binding and adapter-based fetching.
- `cube_client.py` — Cube REST API client: query builder, filter translation, response transformer. Exports `fetch_from_cube_model(...)` used by the Cube adapter when rows are not provided.
- `errors.py` — `NoDataSourceError(ValueError)`: raised when no data source is available.
- `duckdb_adapter.py` — DuckDB query adapter for file-backed data sources. Three layers: `resolve_measure_expressions()` ({{ ref }} substitution via topological sort), `build_sql()` (SELECT/FROM/WHERE/GROUP BY assembly), `DuckDBAdapter.fetch()` (DuckDB execution). Registered as `"file"` source type. DuckDB imported lazily so the module works without duckdb installed.
- `sources.py` — `DataSourceAdapter` protocol and registry. `CubeDataSourceAdapter` and `DuckDBAdapter` register themselves at import time.

## Key Design Decisions

- **Two modes:** Inline data binding (`bind_data`) vs. Cube.dev fetching (`fetch_from_cube_model` via `resolve_data`). The CLI/dev server calls `resolve_data`, which picks the right one based on whether `--data` / rows are provided.
- **Cube prefix stripping:** Cube returns keys like `orders.field_name` — `cube_client.py` strips to just `field_name` to match DSL conventions.
- **Filter push-down:** DSL `ShelfFilter` operators are translated to Cube filter format and pushed to the API, not filtered client-side.
- **Environment:** Cube integration requires `CUBE_API_URL` and `CUBE_API_TOKEN` env vars.
