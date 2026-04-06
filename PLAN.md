# Implementation Plan: Charter — AI-Native Visual Analytics Platform

## Pipeline

```
YAML chart spec
    → Pydantic validation (ChartSpec)
    → Translator (Vega-Lite dict)
    → Theme merge
    → Data bind
    → HTML render (Phase 1) / Charter Studio (Phase 5) / Web app (Phase 6)
```

---

## Phasing

### Phase 1 — Single Measure + Stacked Multi-Measure (no layers)

The core pipeline. Covers single-mark charts, all encoding channels,
filters, sort, faceting, AND multi-measure stacked panels (repeat/concat).
No layers/multi-axis yet.

### Phase 1a — Layers (multi-axis)

Adds the `layer` property on MeasureEntry. Overlaid marks sharing an axis,
with independent/shared scale resolution. Layers nest inside stacked panels
(the "stacked layers" pattern).

### Phase 2+ — Theme pipeline, semantic layer, layout DSL, Charter Studio, web app

See Future Phases table at the bottom.

---

## Multi-Measure DSL Design

### Constraint

At most ONE of rows/cols can have multiple measures. The other is a single
field (dimension or measure). No 2×2.

### The three shelf shapes

```yaml
# Shape 1: Single field (string) — simplest case
rows: revenue

# Shape 2: List of measure entries — multiple measures
rows:
  - measure: revenue
    mark: bar
    color: country
  - measure: orders
    mark: line

# Shape 3: Measure entry with layers — multi-axis (Phase 1a)
rows:
  - measure: revenue
    mark: bar
    color: country
    layer:
      - measure: arpu
        mark:
          type: line
          style: dashed
        color: "#666666"
    axis: independent
```

### Inheritance rules

Encoding properties cascade: top-level → measure entry → layer entry.
More specific wins.

```
marks: line              # Level 0 default
color: country           # Level 0 default
  └── rows[0].mark: bar     # Level 1 override for this entry
  └── rows[0].color         # Not set → inherits "country"
        └── rows[0].layer[0].mark: line (dashed)   # Level 2 override
        └── rows[0].layer[0].color: "#666666"       # Level 2 override
```

### Translation mapping

| DSL shape | Vega-Lite output |
|-----------|-----------------|
| `rows: "field"` | Single `encoding.y` (Phase 1) |
| `rows: [entry]` (1 entry, no layer) | Single `encoding.y` (same as string) |
| `rows: [entry, entry, ...]` (no layers) | `repeat` or `vconcat` |
| `rows: [entry with layer]` (1 entry) | `layer` array |
| `rows: [entry with layer, entry, ...]` (mixed) | `vconcat` of layer + simple specs |

---

## Phase 1 — What It Supports

### Chart Patterns (single measure, single mark)

| Pattern        | marks    | Key DSL properties                     |
|---------------|----------|----------------------------------------|
| Simple bar    | bar      | cols: dim, rows: measure               |
| Grouped bar   | bar      | + color: dim                           |
| Stacked bar   | bar      | + color: dim (default stacking)        |
| Line chart    | line     | cols: temporal dim, rows: measure      |
| Multi-line    | line     | + color: dim                           |
| Area / Stacked| area     | same patterns as line                  |
| Scatter       | circle   | both axes are measures                 |
| Heatmap       | rect     | two dims + measure on color            |
| Pie / Donut   | arc      | theta encoding                         |
| Point / Tick  | point/tick| strip plots, dot plots                |
| KPI           | text     | + kpi property (special template)      |

### Stacked Multi-Measure (no layers)

```yaml
# Three panels stacked vertically, shared x-axis
cols: week
marks: line
rows:
  - measure: revenue
  - measure: orders
  - measure: arpu
```

```yaml
# Different marks per panel
cols: week
rows:
  - measure: revenue
    mark: bar
    color: country
  - measure: orders
    mark: line
```

### Faceting (combinable with everything above)

| Facet type   | DSL trigger                       |
|-------------|-----------------------------------|
| Row facet   | facet.row: dimension              |
| Column facet| facet.column: dimension           |
| Grid facet  | facet.row + facet.column          |
| Wrap facet  | facet.field + facet.columns: N    |

### Encoding Channels

- `color` — field mapping (categorical/sequential) or fixed hex
- `detail` — disaggregation without visual encoding
- `size` — field mapping or fixed value
- `tooltip` — simple list or list with format strings
- `sort` — by field value, by encoding, or explicit order

### Filters

- Shelf filters (hardcoded): in, not_in, eq, neq, gt, lt, gte, lte, between

---

## Phase 1a — What It Adds

### Layers (multi-axis overlay)

```yaml
cols: week
rows:
  - measure: revenue
    mark: bar
    color: country
    detail: country
    layer:
      - measure: arpu
        mark:
          type: line
          style: dashed
        color: "#666666"
    axis: independent
```

### Stacked layers (panels where some have layers)

```yaml
cols: week
rows:
  - measure: revenue
    mark: bar
    layer:
      - measure: arpu
        mark: line
    axis: independent

  - measure: orders
    mark: line
```

### Triple/quad axis (N layers, no cap)

```yaml
cols: week
rows:
  - measure: revenue
    mark: bar
    layer:
      - measure: arpu
        mark: line
      - measure: margin_pct
        mark: area
        opacity: 0.3
    axis: independent
```

### What changes in the codebase

| File | Change |
|------|--------|
| `chart_schema.py` | Add `LayerEntry` model, add `layer` + `axis` fields to `MeasureEntry` |
| `translator/translate.py` | Route layer entries to `compile_layers()` |
| `translator/patterns/layers.py` | New: compile a MeasureEntry with layers into a VL `layer` spec |
| `translator/patterns/stacked.py` | Update: handle mixed stacked+layered panels via `vconcat` |
| `translator/encodings.py` | Extract `build_color`, `build_tooltip` etc. as public helpers |

---

## File Structure

```
charter/
├── PLAN.md
├── pyproject.toml
├── README.md
│
├── src/
│   ├── __init__.py                  # Public API
│   ├── schema/
│   │   ├── __init__.py
│   │   ├── chart_schema.py          # Pydantic models (Phase 1 + 1a shapes)
│   │   ├── field_types.py           # Dimension vs measure type resolution
│   │   └── layout_schema.py         # Layout DSL: DashboardSpec, component models, resolve_child
│   ├── translator/
│   │   ├── __init__.py
│   │   ├── translate.py             # Main router: detect spec shape → delegate
│   │   ├── encodings.py             # Encoding channel builders (shared helpers)
│   │   ├── marks.py                 # Mark type → VL mark object
│   │   ├── filters.py               # DSL filters → VL transforms
│   │   ├── sort.py                  # DSL sort → VL encoding sort
│   │   ├── facet.py                 # Facet wrapping (inner-spec-agnostic)
│   │   ├── layout.py              # Layout DSL → HTML translator
│   │   ├── layout_styles.py       # Style resolution engine for layout
│   │   └── patterns/
│   │       ├── __init__.py
│   │       ├── single.py            # Single-measure chart (Phase 1 path)
│   │       ├── stacked.py           # Multi-measure stacked panels (Phase 1)
│   │       └── layers.py            # Layer compilation (Phase 1a)
│   ├── theme/
│   │   ├── __init__.py
│   │   ├── merge.py
│   │   └── default_theme.json
│   ├── data/
│   │   ├── __init__.py
│   │   └── bind.py
│   ├── render/
│   │   ├── __init__.py
│   │   └── to_html.py
│   ├── compose/
│   │   ├── __init__.py
│   │   └── dashboard.py           # End-to-end dashboard composition
│   └── cli/
│       ├── __init__.py
│       └── render.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── yaml/
│   │   │   ├── simple_bar.yaml          # Phase 1: single measure
│   │   │   ├── grouped_bar.yaml
│   │   │   ├── line_chart.yaml
│   │   │   ├── multi_line.yaml
│   │   │   ├── scatter.yaml
│   │   │   ├── heatmap.yaml
│   │   │   ├── facet_row.yaml
│   │   │   ├── facet_wrap.yaml
│   │   │   ├── stacked_panels.yaml      # Phase 1: multi-measure stacked
│   │   │   ├── stacked_diff_marks.yaml  # Phase 1: different marks per panel
│   │   │   ├── dual_axis.yaml           # Phase 1a: two layers
│   │   │   ├── triple_axis.yaml         # Phase 1a: three layers
│   │   │   ├── stacked_layers.yaml      # Phase 1a: stacked + layers mixed
│   │   │   └── layers_faceted.yaml      # Phase 1a: layers + facet
│   │   ├── data/
│   │   │   └── orders.json
│   │   └── layout/
│   │       ├── minimal.yaml
│   │       ├── kpi_dashboard.yaml
│   │       ├── sidebar_dashboard.yaml
│   │       ├── predefined_components.yaml
│   │       ├── compose_minimal.yaml
│   │       ├── compose_multi.yaml
│   │       ├── compose_with_text.yaml
│   │       ├── compose_predefined.yaml
│   │       └── compose_fit.yaml
│   ├── test_schema.py
│   ├── test_layout_schema.py              # Layout DSL schema parsing + validation
│   ├── test_layout_translator.py          # Layout translator tests
│   ├── test_translator.py
│   ├── test_facet.py
│   ├── test_stacked.py                  # Phase 1: stacked panel tests
│   ├── test_layers.py                   # Phase 1a: layer tests
│   ├── test_render.py
│   └── test_dashboard_compose.py          # Dashboard composition + CLI tests
│
└── docs/
    ├── DSL_Specification.md
    ├── Architecture.md
    ├── Vision.md
    ├── DESIGN_final_multi_measure.md
    ├── Layout_DSL_Specification.md
    ├── Charter_Studio_Design.md
    └── plans/                           # Per-ticket plan documents
        └── TICKET-ID.md
```

---

## Implementation Steps

### Phase 1

**Step 1: Bootstrap + Schema** ✅ DONE
- pyproject.toml, Pydantic models, YAML fixtures, first tests passing

**Step 2: Core Translator** ✅ DONE
- Single-measure: encodings, marks, filters, sort
- 24 tests green

**Step 3: Extend Schema for Multi-Measure** (IN PROGRESS)
- Add `MeasureEntry` model (measure + mark + color + detail + size + opacity)
- Add `LayerEntry` model with `layer` and `axis` fields (parsed but not compiled yet)
- Extend `rows`/`cols` type: `Union[str, list[MeasureEntry]]`
- Add validator: at most one multi-measure shelf
- Add stacked YAML fixtures, verify they parse

**Step 4: Stacked Panels Translator**
- Refactor `translate.py` to detect spec shape and route:
  - `rows` is string → `patterns/single.py` (existing Phase 1 logic)
  - `rows` is list, no layers → `patterns/stacked.py`
- Extract shared encoding helpers from `encodings.py`
- `stacked.py`: compile to VL `repeat` (uniform marks) or `vconcat` (mixed marks)
- Handle stacked + facet combination
- Tests: stacked_panels.yaml, stacked_diff_marks.yaml

**Step 5: Theme + Data + CLI** ✅ DONE
- merge_theme, bind_data, render_html, CLI all working

**Step 6: KPI Pattern** (stretch)
- marks: text + kpi property → specialized template

### Phase 1a

**Step 7: Layer Compilation**
- Activate `LayerEntry.layer` and `MeasureEntry.axis` in translator
- `patterns/layers.py`: compile MeasureEntry with layers into VL `layer` array
- Mark/color/detail inheritance: entry inherits from top-level, layer inherits from entry
- Axis resolution: `axis: independent` → `resolve: {scale: {y: "independent"}}`
- Tests: dual_axis.yaml, triple_axis.yaml

**Step 8: Stacked Layers**
- Update `stacked.py`: when a stacked entry has `layer`, compile it as a
  layer spec within the vconcat
- Tests: stacked_layers.yaml

**Step 9: Layers + Facet**
- facet.py already wraps any inner spec — verify it works with layer specs
- Tests: layers_faceted.yaml

---

## Key Design Decisions

### Measure entries, not parallel arrays
Each measure carries its own mark/color/detail. No zipping across
separate lists. Readable for humans, reliable for LLMs.

### Layers nest inside measure entries
A `layer` block on a measure entry means "overlay these additional measures
in the same chart space." The parent measure is the primary; layers are
additions. This keeps the mark right next to its measure.

### Inheritance: top-level → entry → layer
`marks: line` at top level acts as default. Entry-level `mark: bar` overrides.
Layer-level `mark: {type: line, style: dashed}` overrides the entry.
Same for color, detail, size.

### Only one multi-measure shelf
At most one of rows/cols can be a list. Schema validator enforces this.
Eliminates 2×2 ambiguity entirely.

### facet.py is inner-spec-agnostic
Wraps `{mark, encoding}`, `{layer: [...]}`, or `{vconcat: [...]}` identically.
No changes needed when adding layers or stacked panels.

### Pattern-based translator routing
`translate.py` inspects the spec shape and delegates:
```python
if rows is str and cols is str:    → patterns/single.py
if rows is list (no layers):       → patterns/stacked.py
if rows is list (has layers):      → patterns/stacked.py (which calls layers.py per entry)
```

---

## AI Development Workflow

### Two-Tier Model
- **Opus (architect):** Reads a Jira ticket + all context files, produces a detailed plan document to `docs/plans/TICKET-ID.md`. Plan includes schema changes, typed function signatures with pseudocode, translation rule lookup tables, inheritance resolution pseudocode, edge case tables, per-test fixture/expected-output pairs, verbatim documentation deltas, and an explicit Out of Scope section.
- **Sonnet/Haiku (implementer):** Reads the plan document and executes it mechanically. No architectural decisions — the plan is the spec.

### charter-planner Skill
A Claude Code skill that automates the planning workflow: fetches the Jira ticket via MCP, ingests project context files, and outputs the structured plan document.

### Per-Ticket Plan Documents
Every Jira ticket gets a plan document at `docs/plans/TICKET-ID.md` before any code is written. Test fixtures (input YAML + expected Vega-Lite JSON) are specified upfront. Documentation deltas are explicit.

---

## Dependencies

```
Runtime: pydantic >= 2.0, pyyaml >= 6.0
Dev: pytest >= 8.0, syrupy >= 4.0 (snapshot testing)
```

---

## Future Phases

| Phase | Adds | Key files |
|-------|------|-----------|
| **2** | Theme pipeline (Figma → Style Dictionary) | `theme/`, `tools/` |
| **4** | Layout DSL (dashboards, static HTML) | `schema/layout_schema.py`, `translator/layout.py` |
| **5** | Charter Studio (local dev server + native app) | `studio/` |
| **6** | Web app (hosted, business users) | `app/` |
| **7** | Production (VegaFusion, caching, auth) | Infrastructure |
