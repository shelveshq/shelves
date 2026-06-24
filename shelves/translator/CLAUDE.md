# Translator — CLAUDE.md

This module handles **Translate**: `ChartSpec` → Vega-Lite dict, and the Layout
DSL: `DashboardSpec` → HTML.

## Chart files

- `translate.py` — Chart entry point (`translate_chart`). Routes based on shelf shape.
- `encodings.py` — Builds Vega-Lite encoding channels from shelves
- `filters.py` — Translates DSL `ShelfFilter` to Vega-Lite transform filters
- `sort.py` — Sort encoding generation
- `marks.py` — Mark type mapping and mark property generation
- `labels.py` — Builds `usermeta` label intent for the compile-then-patch label architecture (placement happens browser-side; see `shelves/render/CLAUDE.md`)
- `resolution.py` — Mark and property cascade helpers (3-level: layer > entry > top-level)
- `panel.py` — Panel encoding builder for stacked/layered panels (shared axis, measure axis, color/detail/size/tooltip/sort)
- `facet.py` — Facet wrapping; applies uniformly to any inner spec shape

### Patterns (`patterns/`)

- `single.py` — String shelves → single-measure charts
- `stacked.py` — List shelves → multi-measure: same marks use `repeat`, different marks use `vconcat`/`hconcat`. Delegates to `layers.py` when any entry has `.layer`
- `layers.py` — Layer entries → dual/multi-axis and stacked layers (implemented)

## Layout DSL files

- `layout.py` — Dashboard entry point (`translate_dashboard`): layout tree → HTML
- `layout_flatten.py` — Flattens the dashboard tree into `FlatNode`s for the solver
- `layout_solver.py` — Fixed-size box solver that assigns pixel dimensions to nodes
- `layout_styles.py` — Style resolution engine (shared style rules, presets, padding)

## Routing Logic

The translator routes based on shelf shape:
1. String shelves → `patterns/single.py`
2. List shelves → `patterns/stacked.py`
3. Layer entries → `patterns/layers.py`

Facet wrapping (`facet.py`) applies as a wrapper around any inner spec shape.

## Design Principles

- The translator consumes the `FieldTypeResolver` protocol — it does not know where type information comes from.
- Each pattern module produces a self-contained Vega-Lite spec fragment.
- Inheritance (marks/color/detail) is resolved at the schema level before reaching the translator.
