# Design: Multi-Measure Shelves — Final DSL Shape

This is the canonical reference for the multi-measure shelf design.
It covers the constrained, realistic set of multi-measure patterns
that the Chart DSL supports.

---

## Constraints

1. At most ONE measure on one shelf, multiple on the other. No 2×2.
2. The multi-measure shelf can be **stacked** (separate panels) or
   **layered** (overlaid multi-axis), or **stacked groups of layers**.
3. No new keywords beyond what's needed. Keep it readable.
4. Mark defined alongside its measure. Top-level mark propagates as default.

---

## The Five Cases

| Case | cols | rows | Visual result |
|------|------|------|---------------|
| **A** | 1 dim | 1 measure | Simple chart (Phase 1) |
| **B** | 1 dim | N measures, each standalone | Stacked panels (repeat) |
| **C** | 1 dim | N measures, overlaid | Multi-axis layers |
| **D** | 1 dim | mix: some standalone, some layered | Stacked panels where some panels have layers |
| **E** | 1 measure | N measures on rows (scatter variants) | Same patterns but axes flipped |

Case D is the most complex realistic case — "stacked layers."

---

## Case A: Simple chart (unchanged)

```yaml
cols: week
rows: revenue
marks: bar
color: country
```

Exactly as Phase 1. No changes.

---

## Case B: Stacked panels (N measures, each its own panel)

When `rows` is a list of measure objects, they stack:

```yaml
cols: week
rows:
  - measure: revenue
    mark: bar
  - measure: orders
    mark: line
  - measure: arpu
    mark: line
```

**Reading this:** "On the y-axis, give me three panels — revenue as bars,
orders as a line, arpu as a line. All share the x-axis (week)."

Three items in the list → three stacked panels. Each carries its own mark.

**Default mark propagation:** If you define `marks` at the top level, rows
entries inherit it:

```yaml
cols: week
marks: line          # Default for all panels

rows:
  - measure: revenue
    mark: bar        # Override: bars for revenue
  - measure: orders  # Inherits line
  - measure: arpu    # Inherits line
```

Even shorter — if every panel uses the same mark:

```yaml
cols: week
marks: line
rows:
  - measure: revenue
  - measure: orders
  - measure: arpu
```

**Translation:** Vega-Lite `repeat` with `row`:

```json
{
  "repeat": {"row": ["revenue", "orders", "arpu"]},
  "spec": {
    "mark": "line",
    "encoding": {
      "x": {"field": "week", "type": "temporal"},
      "y": {"field": {"repeat": "row"}, "type": "quantitative"}
    }
  }
}
```

When marks differ per panel, we use `concat` instead of `repeat` (since
each panel needs its own mark definition).

---

## Case C: Layered multi-axis (N measures overlaid in one chart)

When a row entry has a `layer` key, those measures share one panel:

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
```

**Reading this:** "On the y-axis, plot revenue as bars colored by country.
Layered on top of that, plot arpu as a dashed line in grey."

The first measure (`revenue`) is the primary. The `layer` list contains
additional measures overlaid on the same chart space.

**Why this shape works:**
- The mark is right next to its measure
- The layer is visually nested under the measure it shares space with
- No new keyword — `layer` is descriptive and scoped under the measure
- For a pure multi-axis with no "primary" (just peers), pick either as primary

**Axis independence:**

```yaml
cols: week
rows:
  - measure: revenue
    mark: bar
    layer:
      - measure: arpu
        mark: line
    axis: independent     # Each measure gets its own y-scale
```

`axis: independent` at the row-entry level affects all layers within that entry.

**Translation:** Vega-Lite `layer`:

```json
{
  "layer": [
    {
      "mark": "bar",
      "encoding": {
        "x": {"field": "week", "type": "temporal"},
        "y": {"field": "revenue", "type": "quantitative"}
      }
    },
    {
      "mark": {"type": "line", "strokeDash": [6, 4]},
      "encoding": {
        "x": {"field": "week", "type": "temporal"},
        "y": {"field": "arpu", "type": "quantitative"}
      }
    }
  ],
  "resolve": {"scale": {"y": "independent"}}
}
```

---

## Case D: Stacked panels, some with layers

This is the most complex realistic case. Say you want:
- Panel 1: revenue bars + ARPU trend line (layered)
- Panel 2: orders as a standalone line

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

  - measure: orders
    mark: line
```

**Reading this:** "Two stacked panels. The first has revenue bars with an
ARPU line layered on top (independent axes). The second is just orders
as a line."

The list has two items → two panels. The first item has a `layer` block
so it becomes a multi-axis panel. The second is a simple single-measure panel.

**Translation:** Vega-Lite `vconcat` where the first child is a `layer` spec
and the second is a simple spec:

```json
{
  "vconcat": [
    {
      "layer": [
        {"mark": "bar", "encoding": {"x": {...}, "y": {"field": "revenue"}, "color": {...}}},
        {"mark": {"type": "line", "strokeDash": [6, 4]}, "encoding": {"x": {...}, "y": {"field": "arpu"}}}
      ],
      "resolve": {"scale": {"y": "independent"}}
    },
    {
      "mark": "line",
      "encoding": {"x": {...}, "y": {"field": "orders"}}
    }
  ]
}
```

---

## Case E: Flipped — measure on cols, multi-measure on rows

Everything above works symmetrically. If `cols` has the multi-measure
list, panels stack horizontally instead of vertically, and layers
share the y-axis with independent x-axes:

```yaml
rows: week
cols:
  - measure: revenue
    mark: bar
  - measure: orders
    mark: line
```

Two panels side by side. Revenue bars on the left, orders line on the right.

Translation uses `hconcat` instead of `vconcat`, or `repeat` with `column`.

---

## Top-level mark as default

When `marks` is defined at the top level, it becomes the default
for all entries:

```yaml
cols: sales
marks: circle          # Default for all layers/panels

rows:
  - measure: revenue   # scatter: sales vs revenue
  - measure: orders    # scatter: sales vs orders
  - measure: arpu      # scatter: sales vs arpu
```

The mark default comes from top-level `marks:`, not from the cols block.
This keeps `cols` clean — it's always just a field name (string).

---

## Complete Grammar for `rows` (and symmetrically `cols`)

```yaml
# Shape 1: Single field (string) — Phase 1, unchanged
rows: revenue

# Shape 2: List of measure entries — multi-measure
rows:
  - measure: revenue               # Required: field name
    mark: bar                      # Optional: mark for this entry (or inherit)
    color: country                 # Optional: color for this entry (or inherit)
    detail: country                # Optional: detail (or inherit)
    size: 200                      # Optional: size (or inherit)
    opacity: 0.8                   # Optional: mark opacity
    axis: independent              # Optional: axis scale resolution for layers
    layer:                         # Optional: additional measures layered here
      - measure: arpu
        mark:
          type: line
          style: dashed
        color: "#666666"
        detail: null
```

A row entry WITHOUT `layer` is a standalone panel.
A row entry WITH `layer` is a multi-axis panel.
Multiple row entries stack as panels.

---

## Inheritance Rules

Encoding properties cascade: top-level → row entry → layer entry.
More specific wins.

```
Top-level marks/color/detail/size
  └── applies to all row entries that don't specify their own
        └── applies to all layer entries that don't specify their own
```

```yaml
marks: line                # Level 0: default for everything
color: country             # Level 0: default for everything

rows:
  - measure: revenue
    mark: bar              # Level 1: overrides line → bar for this panel
    # color: country       # Inherited from Level 0
    layer:
      - measure: arpu
        mark:              # Level 2: overrides for this layer only
          type: line
          style: dashed
        color: "#666666"   # Level 2: overrides country → fixed grey
```

Resulting marks: revenue=bar, arpu=dashed line.
Resulting colors: revenue=country, arpu=#666666.

---

## All the Worked Examples

### 1. Classic dual-axis (revenue bars + ARPU line)

```yaml
sheet: "Revenue & ARPU by Week"
data:
  model: orders
  measures: [revenue, arpu]
  dimensions: [country, week]
  time_grain:
    field: week
    grain: week

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

tooltip: [week, country, revenue, arpu]
```

### 2. Triple-axis (three measures overlaid)

```yaml
sheet: "Revenue, ARPU & Margin"
data:
  model: orders
  measures: [revenue, arpu, margin_pct]
  dimensions: [week]
  time_grain: { field: week, grain: week }

cols: week
rows:
  - measure: revenue
    mark: bar
    color: "#4A90D9"
    layer:
      - measure: arpu
        mark:
          type: line
          point: true
        color: "#E5A84B"
      - measure: margin_pct
        mark: area
        opacity: 0.3
        color: "#5BBD72"
    axis: independent

tooltip: [week, revenue, arpu, margin_pct]
```

### 3. Three stacked panels, same mark

```yaml
sheet: "Key Metrics"
data:
  model: orders
  measures: [revenue, orders, arpu]
  dimensions: [week]
  time_grain: { field: week, grain: week }

cols: week
marks: line

rows:
  - measure: revenue
  - measure: orders
  - measure: arpu

tooltip: [week]
```

### 4. Stacked panels, different marks

```yaml
sheet: "Revenue and Orders"
data:
  model: orders
  measures: [revenue, orders]
  dimensions: [week]
  time_grain: { field: week, grain: week }

cols: week
rows:
  - measure: revenue
    mark: bar
    color: country
  - measure: orders
    mark: line
    color: country

tooltip: [week, country]
```

### 5. Stacked layers (panels where one panel has layers)

```yaml
sheet: "Revenue+ARPU Panel, Orders Panel"
data:
  model: orders
  measures: [revenue, arpu, orders]
  dimensions: [week]
  time_grain: { field: week, grain: week }

cols: week
rows:
  - measure: revenue
    mark: bar
    layer:
      - measure: arpu
        mark:
          type: line
          style: dashed
        color: "#666666"
    axis: independent

  - measure: orders
    mark: line

tooltip: [week, revenue, arpu, orders]
```

### 6. Revenue vs target vs forecast (shared axis, same unit)

```yaml
sheet: "Revenue vs Plan"
data:
  model: orders
  measures: [revenue, target, forecast]
  dimensions: [month]
  time_grain: { field: month, grain: month }

cols: month
rows:
  - measure: revenue
    mark: line
    color: "#4A90D9"
    layer:
      - measure: target
        mark:
          type: line
          style: dashed
        color: "#cccccc"
      - measure: forecast
        mark:
          type: line
          style: dotted
        color: "#E5A84B"
    # No axis: independent → shared y-axis (all are $ values)

tooltip: [month, revenue, target, forecast]
```

### 7. Bars by country + overall average line

```yaml
sheet: "Revenue by Country + Average"
data:
  model: orders
  measures: [revenue, avg_revenue]
  dimensions: [country]

cols: country
rows:
  - measure: revenue
    mark: bar
    color: country
    layer:
      - measure: avg_revenue
        mark: rule
        color: "#666666"
        detail: null

sort:
  field: revenue
  order: descending
tooltip: [country, revenue, avg_revenue]
```

### 8. With faceting (layers inside faceted panels)

```yaml
sheet: "Revenue & ARPU by Week, by Region"
data:
  model: orders
  measures: [revenue, arpu]
  dimensions: [region, week]
  time_grain: { field: week, grain: week }

cols: week
rows:
  - measure: revenue
    mark: bar
    layer:
      - measure: arpu
        mark:
          type: line
          style: dashed
        color: "#E5A84B"
    axis: independent

facet:
  row: region

tooltip: [week, region, revenue, arpu]
```

### 9. Scatter variant — measure on cols, stacked on rows

```yaml
sheet: "Sales vs Multiple Metrics"
data:
  model: orders
  measures: [sales, revenue, orders, arpu]
  dimensions: [country]

cols: sales
marks: circle
color: country

rows:
  - measure: revenue
  - measure: orders
  - measure: arpu

tooltip: [country, sales]
```

Three scatter panels stacked vertically: sales vs revenue,
sales vs orders, sales vs arpu.

---

## Pydantic Schema

```python
class LayerEntry(BaseModel):
    """A measure layered on top of a parent row/col entry."""
    measure: str
    mark: MarkSpec | None = None
    color: ColorSpec | None = None
    detail: str | None = None
    size: str | int | float | None = None
    opacity: float | None = Field(None, ge=0.0, le=1.0)


class MeasureEntry(BaseModel):
    """One entry on the multi-measure shelf (row or col)."""
    measure: str
    mark: MarkSpec | None = None
    color: ColorSpec | None = None
    detail: str | None = None
    size: str | int | float | None = None
    opacity: float | None = Field(None, ge=0.0, le=1.0)
    axis: Literal["independent", "shared"] | None = None
    layer: list[LayerEntry] | None = None


# A shelf is either a single field name or a list of measure entries
ShelfSpec = Union[str, list[MeasureEntry]]


class ChartSpec(BaseModel):
    # ...
    cols: ShelfSpec | None = None
    rows: ShelfSpec | None = None
    # ...

    @model_validator(mode="after")
    def at_most_one_multi_measure_shelf(self):
        """Only one of rows/cols can be a multi-measure list."""
        rows_multi = isinstance(self.rows, list)
        cols_multi = isinstance(self.cols, list)
        if rows_multi and cols_multi:
            raise ValueError(
                "Only one of rows/cols can have multiple measures. "
                "Use the single-field shelf for the other axis."
            )
        return self
```

---

## Translation Logic

```python
def translate_chart(spec: ChartSpec) -> dict:
    # Determine which shelf is multi-measure (if any)
    rows_is_multi = isinstance(spec.rows, list)
    cols_is_multi = isinstance(spec.cols, list)

    if not rows_is_multi and not cols_is_multi:
        # Phase 1 path: single mark chart
        return compile_single(spec)

    if rows_is_multi:
        return compile_multi_rows(spec)

    if cols_is_multi:
        return compile_multi_cols(spec)


def compile_multi_rows(spec: ChartSpec) -> dict:
    entries = spec.rows  # list[MeasureEntry]
    shared_x = build_x_encoding(spec.cols, resolver)

    if len(entries) == 1 and entries[0].layer:
        # Single entry with layers → pure layer spec (no concat)
        return compile_layer_entry(entries[0], shared_x, spec)

    if all(e.layer is None for e in entries):
        # All standalone → repeat or concat
        return compile_stacked_entries(entries, shared_x, spec)

    # Mix of standalone and layered → vconcat
    panels = []
    for entry in entries:
        if entry.layer:
            panels.append(compile_layer_entry(entry, shared_x, spec))
        else:
            panels.append(compile_single_entry(entry, shared_x, spec))

    return {"vconcat": panels}
```
