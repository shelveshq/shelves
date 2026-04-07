# Changelog

All notable changes to this project will be documented in this file.

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
- MIT license
