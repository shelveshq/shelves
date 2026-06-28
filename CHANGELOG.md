# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.4.0] - 2026-06-28

### Charts

- **Data labels** — marks can now carry text labels driven by a field or measure. Bar/column and layered/dual-axis charts position labels deterministically and only render the ones that fit, via a compile-then-patch architecture that patches the compiled Vega spec in the browser rather than emitting extra Vega-Lite layers. (KAN-269, KAN-278, KAN-279)
- **Heatmap cell labels** — `rect` (heatmap) cells support data labels with a deterministic centre placement and a fit gate that suppresses labels too large for their cell. (KAN-307)
- **Axis grid / ruler / tick / label toggles** — charts expose per-axis `grid`, `ruler`, `ticks`, and `labels` toggles, with a themeable default for gridlines. (KAN-306)

### Dashboards

- **Independent dashboard legends** — a dashboard can declare standalone `legend` components that link to sheets by field name, sharing a single color scale across the linked sheets. Legend scales are resolved in the browser at render time, and sheet/legend DOM ids are assigned once at flatten time. (SHE-9, SHE-10, SHE-11, SHE-28, SHE-29)
- **Layout polish pass** — refined solver ↔ Vega-Lite sizing and CSS for stacked/facet sheets, padding clipping, and text/container alignment. (KAN-290)
- **Image `fit` / `center` controls** — `image` components now accept `fit` (when `true`, scale to fit the box preserving aspect ratio; when `false`, render at natural size and scroll on overflow) and `center` (when `true`, center within the box; when `false`, anchor top-left — applies only when `fit: true`). Defaults are `fit: true`, `center: false`. (KAN-297)
- **Asset-relative image paths** — a dashboard `image:` src is now interpreted relative to the assets directory (e.g. `image: png/logo.png`), consistent with how `sheet:` is named relative to the charts directory. External URLs and `data:` URIs pass through unchanged. The renderer emits the correct relative URL per pipeline (studio/dev serve `/assets/…`; `shelves-render` emits a path relative to the output HTML). `--assets-dir` is now available on `shelves-render` and `shelves-dev` as well as `shelves-studio` (default `<dir>/assets`). (KAN-308)

### Studio

- **`--reload` flag** — `shelves-studio` accepts `--reload` to auto-reload the server on source changes during development.
- **`shelves-studio` port-collision handling** — the CLI now pre-checks the bind port and exits with a clear "Port N already in use" message *before* printing the startup banner or opening a browser tab, instead of opening a dead tab and then crashing with a bind traceback. The advertised/opened URL now uses the loopback IP `127.0.0.1` (matching the bind host) rather than `localhost`, which on macOS can resolve to IPv6 and hit an unrelated listener such as a Docker container on port 5173. (KAN-261)
- **Dashboard preview scrolls on overflow** — at `100%` / `50%` zoom, a dashboard whose scaled canvas is larger than the preview pane now scrolls (vertical + horizontal) so the whole canvas is reachable, instead of being clipped. `Fit` is unaffected. (KAN-298)
- **Project assets served in the preview** — `shelves-studio` now serves files under the project's `assets/` directory at `/assets/…`, so dashboard images load in the preview iframe. Add `--assets-dir <path>` to override the location (default `<dir>/assets`); the directory need not exist at startup — an `assets/` added later is served without restarting. (KAN-297)

### Internal

- Renamed the remaining "Charter" references to "Shelves" across the codebase.
- Refreshed `CLAUDE.md` files and the architecture diagram for the current scope.
- Added a public `returncode` property to `PtyManager`. (SHE-26)

## [0.3.1] - 2026-06-14

### Packaging

- Fixed missing `default_theme.yaml` in package data — installed environments (Studio, pip installs) would crash with `FileNotFoundError`

## [0.3.0] - 2026-06-13

### Data

- **Flat-file data sources** — models can now point a `source.type: file` block at a local CSV, Parquet, or JSON file, queried directly with DuckDB. No Cube.dev instance required to render a chart.
- **DuckDB query adapter** — file-backed models compile to DuckDB SQL with `{{ ref }}` measure substitution, filter push-down, and aggregation/group-by assembly. Install via the optional `shelves-bi[duckdb]` extra.
- **`shelves-import` CLI** — auto-generate a ready-to-use model from a CSV, Parquet, or JSON file. String columns become dimensions, numeric columns become `sum` measures, and date columns become temporal dimensions. Supports `--name`, `--models-dir`, and `--overwrite`.

### Docs

- README and Getting Started rewritten around the two data paths: start with a flat file, or connect to a Cube.dev semantic layer. Both paths share the same model and chart schema.

## [0.2.1] - 2026-04-21

### Packaging

- Moved studio dependencies (`fastapi`, `uvicorn`, `watchfiles`, `websockets`, `watchdog`) into core dependencies so `pip install shelves-bi` works without extras

## [0.2.0] - 2026-04-20

### Studio

- **UI polish pass** — restructured layout with proper grid-based panels, improved responsive behavior
- **State management overhaul** — centralized reactive state with proper change propagation
- **Preview rendering** — robust iframe lifecycle, forced re-render on compile, stale result discarding
- **Error recovery** — graceful handling of failed dashboard compiles with clear error display
- **Monaco editor fixes** — resolved cursor jump on save, configured worker URLs for YAML language service
- **Visual improvements** — eliminated resize flicker and white flash, fixed stale error overlays

## [0.1.0] - 2026-04-07

Initial public release as `shelves-bi` on [PyPI](https://pypi.org/project/shelves-bi/).

### Core

- **YAML DSL** for declarative chart specifications — shelves (`cols`/`rows`), marks, color, detail, size, tooltip, filters, sort, and facet
- **Single-measure charts** — bar, line, area, circle, square, text, point, rule, tick, rect, arc, geoshape
- **Multi-measure stacked panels** — same mark compiles to Vega-Lite `repeat`, mixed marks compile to `vconcat`/`hconcat`
- **Temporal dot notation** — `order_date.month` resolves grain, time unit, and format from the data model
- **Faceting** — row/column facets and wrap facets with configurable axis resolution

### Data Models

- **Semantic model manifests** — define measures, dimensions, labels, formats, aggregations, and sort defaults in reusable YAML files
- **Model resolver** — auto-injects axis titles, formats, legend titles, tooltip labels, grid defaults, and default sort from model metadata
- **Cube.dev integration** — fetch data from Cube REST API with filter push-down and prefix stripping

### Themes

- **Unified theme system** — single `theme.yaml` with `chart` (Vega-Lite config) and `layout` (dashboard tokens) sections
- **Deep merge** — partial theme overrides; only specify what you want to change
- **Text presets** — title, subtitle, heading, body, caption, label with theme-driven typography

### Dashboards

- **Layout DSL** — compose charts, text, images, navigation, and spacers in nested horizontal/vertical containers
- **Border-box solver** — fixed pixel layout with percentage, fixed, and auto sizing
- **Predefined components** — define appearance once, place by name in the layout tree
- **Shared styles** — reusable visual presets (background, border, shadow, etc.)
- **Type-led syntax** — `sheet:`, `text:`, `horizontal:` instead of verbose `type` fields

### CLI

- `shelves-render` — render charts and dashboards to standalone HTML
- `shelves-dev` — live-reload dev server at localhost:8089

### Packaging

- Published as `shelves-bi` on PyPI (`pip install shelves-bi`)
- Import as `import shelves` / `from shelves import ...`
- PEP 561 `py.typed` marker for type checker support
- Apache 2.0 license
