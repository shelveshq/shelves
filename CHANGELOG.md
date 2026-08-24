# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### MCP authoring tools

- **Authoring tools for the MCP server** — `validate_spec`, `compile_chart`, `render_chart` (PNG/HTML), `render_dashboard`, and `query_model`, so an agent can validate, compile, render, and sanity-check data through the same pipeline every other surface uses. (SHE-56)
- **Structured errors, never protocol crashes** — every tool returns errors as a payload. `render_dashboard` now reports missing chart links, compile failures, and invalid dashboard YAML as structured errors (instead of raising) and surfaces per-sheet data/layout warnings. `render_chart` reports missing or malformed inline data, rejects unknown `format` values, and validates `theme` paths for existence and project containment. `query_model` validates filter fields, rejects a non-positive `limit`, and keeps error locations in filter messages.
- **File-source data root fix** — a file (DuckDB) source now resolves its relative `source.path` against the caller's data base directory on every surface, not the current working directory.

## [0.6.0] - 2026-08-01

The **Parameters** release: charts and dashboards can now be parameterized —
values declared once in `parameters.yaml` are substituted at compile time across
field references, filters, titles, and model calculations. Dashboards get
interactive controls that recompile on change in Studio.

### Parameters

- **Four parameter types** — `string`, `number`, `date`, and `list`, each with `default`, optional `values` constraint, and `label`. Declared in `models/parameters.yaml` and referenced as `$name` in chart specs. (SHE-89, SHE-90)
- **Parameterized model calculations** — model measures and dimensions can use `${name}` substitution in their `column` and `expression` fields, enabling a single model definition to serve multiple parameter-driven views. (SHE-91)
- **Dashboard parameter controls** — a `control: <param>` layout leaf renders an interactive widget (dropdown, number input, date picker, text input) whose type is inferred from the parameter declaration. Changing a control in Studio recompiles the dashboard with the new value; in exported HTML, controls render as disabled read-only widgets. (SHE-92)
- **Dashboard text interpolation** — `text` components resolve `${name}` references against the current parameter values before rendering. (SHE-96)
- **`--param` CLI flag** — `shelves-render` and `shelves-dev` accept `--param key=value` to override parameter defaults from the command line. (SHE-93)
- **`--parameters-file` CLI flag** — point at a non-default parameters file location.

### Performance

- **Domain resolution cache** — a TTL-based cache across compiles avoids redundant data-source queries when resolving parameter domains (e.g. distinct values for a dropdown). (SHE-95)

### Internal

- Moved confidential material to a private companion repo (`shelveshq/shelves-internal`), symlinked via `.private/`.
- README rewritten for the landed product positioning.
- Corrected parameter documentation against the shipped code. (SHE-93)

## [0.5.0] - 2026-07-20

The **Shelves Studio — UX & Design-System Polish** release: Studio is brought in
line with the Shelves Design System and its core interaction rough edges are
fixed. No changes to the chart or dashboard DSL — `DSL_VERSION` stays `0.9.0`.

### Studio

- **Design-system adoption** — Studio chrome now renders from Shelves Design System tokens via a bridge layer (`shelves-tokens.css` + `tokens-bridge.css`), covering the topbar, status bar, preview header, file tree, and Monaco theme. Adds the real Shelves wordmark and a synced favicon, DS empty/error states, and inline Lucide icons in the sidebar. (SHE-33, SHE-34, SHE-35, SHE-36, SHE-46)
- **Compile states without the flash** — a stale render now stays visible while recompiling; a 150ms-gated veil dims it with a "Compiling…" pill, so fast compiles are seamless and slow ones show progress. (SHE-37)
- **Data view** — the chart preview's JSON view is replaced by a **Data** view showing the resolved rows behind the current chart, across all three backends (inline, file/DuckDB, Cube). Rendered rows are capped at 500 with a `showing N of M rows` footer; skipped resolution, zero rows, and compile errors each have their own state. (SHE-43)
- **File management from the UI** — create, rename, duplicate, and delete files from the file tree, with starter templates chosen by the configured directory. Renaming the open file preserves the buffer, dirty or not. (SHE-42)
- **Theme file in the explorer** — the `--theme` file appears as a top-level tree entry and theme writes now trigger a recompile of the open buffer. Themes outside the project are reachable by an exact-match alias. Known limitation: external edits to a theme outside the project are not watched. (SHE-44)
- **File navigation history** — back/forward across visited files via topbar chevrons, `Cmd/Ctrl+[` / `Cmd/Ctrl+]`, and mouse buttons 3/4. Entries deleted since being opened are pruned and skipped. The chords deliberately shadow Monaco's outdent/indent; `Tab` / `Shift+Tab` still indent YAML. (SHE-40)
- **Editor correctness and save safety** — the ChartSpec schema is now attached only to chart buffers, so dashboards and models no longer get phantom "Missing property" markers. `Cmd+S` clears the dirty flag only on a confirmed 2xx and surfaces a persistent "Save failed" message otherwise. Dirty buffers prompt before navigation or discard, and a file deleted on disk is never auto-closed. (SHE-48, SHE-65, SHE-51)
- **Sidebar and panes** — the file tree and watcher are scoped to the configured charts/dashboards/models/assets directories instead of the whole project. Collapsing the sidebar leaves a 36px reopen rail (`Cmd/Ctrl+B`), and the editor/preview/terminal splitters use pointer capture so drags survive fast moves and the dashboard iframe. (SHE-39, SHE-41, SHE-38)
- **Integrated terminal** — the terminal now opens reliably against a laid-out container rather than waiting on the socket, so connection failures surface as readable messages instead of a blank box. The shell is a session leader with the PTY as its controlling TTY, making `Ctrl+C` interrupt foreground jobs. Full DS ANSI-16 palette and restyled tab bar. (SHE-47)
- **Compile and status plumbing** — preview, dashboard, and editor handlers ignore watcher broadcasts for files other than the open one; dashboard compile errors reach the status bar; the dashboard loading veil ends when the iframe actually renders; and WebSocket disconnects are visible, escalating to "server unreachable" after repeated failures. (SHE-49, SHE-50, SHE-67, SHE-66)
- **CDN-independent rendering and boot** — vega, vega-lite, vega-embed, and the monaco-yaml worker are vendored same-origin under `static/vendor/`. Studio boot is parallel: the tree, preview, and WebSocket no longer wait on (or fail with) Monaco's load. This also fixes monaco-yaml diagnostics, which were silently dead due to a worker bundle pinned below its peer range. (SHE-77, SHE-64)
- **Host validation and write allow-list** — loopback-only `TrustedHostMiddleware` on every endpoint and mount closes a DNS-rebinding path that binding to 127.0.0.1 never addressed. `PUT /file` enforces the same `.yaml/.yml/.json` allow-list as create/rename/delete. (SHE-52)

### Internal

- Foundational docs (`docs/foundational/`) are now local-only and gitignored, alongside `docs/plans/`. Added `REVIEW.md`.
- `pyrightconfig.json` pointed at `include: ["src"]` — a directory that never existed — so a bare `pyright` run analysed **zero** files and reported success. It now covers `shelves` and `tests` (0 → 136 files), the 483 accumulated errors in the test tree are burned down to zero, and CI runs a bare `pyright` so both trees are gated. Fixed six schema fields that passed their default positionally (`Field(None, …)` → `Field(default=None, …)`), which pyright read as required. (SHE-87)

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
