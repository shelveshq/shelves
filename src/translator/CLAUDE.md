# Translator — CLAUDE.md

This module handles **Translate**: `ChartSpec` → Vega-Lite dict.

## Files

- `translate.py` — Main entry point (`translate_chart`). Routes based on shelf shape.
- `encodings.py` — Builds Vega-Lite encoding channels from shelves
- `filters.py` — Translates DSL `ShelfFilter` to Vega-Lite transform filters
- `sort.py` — Sort encoding generation
- `marks.py` — Mark type mapping and mark property generation
- `facet.py` — Facet wrapping; applies uniformly to any inner spec shape

### Patterns (`patterns/`)

- `single.py` — String shelves → single-measure charts
- `stacked.py` — List shelves → multi-measure: same marks use `repeat`, different marks use `vconcat`/`hconcat`
- `layers.py` — Layer entries (Phase 1a — parsed but raises `NotImplementedError`)

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
