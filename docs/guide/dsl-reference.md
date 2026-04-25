# Shelves DSL Reference

**DSL Version: 0.5.0**

This document is the authoritative reference for the Shelves YAML DSL. It covers every field, what is currently supported, and what is planned but not yet compiled.

## Spec structure

Every chart YAML file is a single document with this top-level shape:

```yaml
version: "0.1.0"          # optional — DSL version this spec targets
sheet: "My Chart Title"    # required — chart name, rendered as the Vega-Lite title
description: "..."         # optional — rendered as the Vega-Lite subtitle

data: orders                 # model name — references a DataModel manifest in models/

cols: <shelf>              # x-axis assignment
rows: <shelf>              # y-axis assignment
marks: bar                 # mark type (required for single-measure charts)

# Optional encoding channels
color: country
detail: country
size: revenue
tooltip: [country, revenue]

# Optional interactions
filters: [...]
sort: {...}

# Optional partitioning
facet: {...}

# Optional axis customization
axis:
  x: { title: "...", format: "...", grid: true }
  y: { title: "...", format: "...", grid: false }
```

---

## Shelves (`cols` / `rows`)

Shelves assign fields to the x-axis (`cols`) and y-axis (`rows`). They come in two shapes:

### Single-measure (string)

```yaml
cols: country
rows: revenue
marks: bar       # required when both shelves are strings
```

Both `cols` and `rows` are plain field names. Top-level `marks` is required.

### Multi-measure (list)

```yaml
cols: week
rows:
  - measure: revenue
  - measure: order_count
  - measure: arpu
```

One shelf is a list of measure entries, the other remains a string. Each entry can override `mark`, `color`, `detail`, `size`, and `opacity`:

```yaml
rows:
  - measure: revenue
    mark: bar
    color: country
  - measure: order_count
    mark: line
    color: country
```

**Constraint:** At most one of `rows`/`cols` can be a list.

### Compilation behavior

- **Same mark across all entries** (or mark inherited from top-level) — compiled as a Vega-Lite `repeat` spec (shared axis, stacked panels).
- **Different marks across entries** — compiled as `vconcat` (rows list) or `hconcat` (cols list).

### Layers (dual/multi-axis)

A measure entry can include a `layer` list to overlay additional measures in the same chart panel:

```yaml
cols: week
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

Each layer entry supports: `measure` (required), `mark`, `color`, `detail`, `size`, `opacity`.

**Encoding inheritance:** Properties cascade top-level → entry → layer. A layer entry with no `mark` inherits from the parent entry, which in turn inherits from top-level `marks`. The same cascade applies to `color`, `detail`, and `size`.

**`detail: null` (explicit)** suppresses inherited detail — useful for reference lines that should aggregate across a grouping dimension:

```yaml
rows:
  - measure: revenue
    mark: bar
    color: country
    detail: country         # bars are per-country
    layer:
      - measure: avg_revenue
        mark: rule
        detail: null          # rule aggregates across countries
```

**`opacity` does NOT cascade** — it's a mark property, applied to whichever level sets it.

**`axis`** controls scale resolution for the measure axis:
- `independent` — each measure gets its own axis scale (different units, e.g. revenue in $ vs ARPU in $/user)
- `shared` (default) — all measures share one axis scale (same units, e.g. revenue vs target both in $)

**`tooltip`, `filters`, and `sort`** are top-level properties: tooltip applies to the primary layer only, filters apply once at the layer-group level, and sort applies to the primary layer's shared axis.

**Note (Phase 1a):** Multi-entry shelves where some entries have layers (e.g. one panel with layers + another standalone panel) raise `NotImplementedError`. Single-entry shelves with layers compile fully.

---

## Temporal dot notation

When using a data model, temporal fields support dot notation to specify the time grain:

```yaml
data: orders
cols: order_date.month    # month grain
rows: revenue
marks: line
```

Supported grains: `day`, `week`, `month`, `quarter`, `year`.

The dot notation resolves to:
- `field`: the base field name (e.g. `order_date`)
- `timeUnit`: the Vega-Lite time unit (e.g. `yearmonth`)
- `axis.format`: auto-injected from the model's per-grain format map (if defined)

Without dot notation, a temporal field uses its `defaultGrain` from the model:

```yaml
cols: order_date    # uses defaultGrain from model (e.g. "month")
```

Dot notation is only valid for fields declared as `type: temporal` in the model. Using it on measures or nominal dimensions raises an error.

---

## Marks

The `marks` field specifies how data points are drawn.

### String shorthand

```yaml
marks: bar
```

Supported mark types: `bar`, `line`, `area`, `circle`, `square`, `text`, `point`, `rule`, `tick`, `rect`, `arc`, `geoshape`.

### Object form

```yaml
marks:
  type: line
  style: dashed      # solid | dashed | dotted
  point: true         # show data points on lines
  opacity: 0.8        # 0.0 to 1.0
```

**Style patterns:** `dashed` renders as `[6, 4]` strokeDash, `dotted` as `[2, 2]`.

---

## Data block

```yaml
data: orders
```

A string referencing a data model file (`models/orders.yaml`). The model defines all measures, dimensions, field types, labels, and formats. See `models/` for available models.

- **Required.** Every chart must reference a model.
- Temporal dimensions, grain, and format strings are all defined in the model — no need to redeclare per chart.

Field type resolution: measures → `quantitative`, dimensions → `nominal`, fields with `type: temporal` in the model (including dot-notation grains like `order_date.month`) → `temporal`.

---

## Color

Three forms:

```yaml
# 1. Dimension name — encodes as nominal color
color: country

# 2. Hex color — static color value
color: "#4A90D9"

# 3. Field mapping — explicit type (useful for quantitative color scales)
color:
  field: revenue
  type: quantitative
```

---

## Detail

Adds a grouping dimension without a visual encoding (e.g., separate lines per country without coloring):

```yaml
detail: country
```

---

## Size

```yaml
# Field-based (quantitative scaling)
size: revenue

# Static value (pixels)
size: 100
```

---

## Tooltip

```yaml
# Simple — list of field names
tooltip: [country, revenue]

# With formatting
tooltip:
  - field: revenue
    format: "$,.0f"
  - field: country
```

---

## Filters

Filters apply as Vega-Lite `transform` entries. Multiple filters are AND-ed.

```yaml
filters:
  # Equality
  - field: country
    operator: eq
    value: "US"

  # Inequality
  - field: country
    operator: neq
    value: "Other"

  # Comparison (gt, lt, gte, lte)
  - field: revenue
    operator: gte
    value: 1000

  # Set membership
  - field: country
    operator: in
    values: ["US", "UK", "DE"]

  # Exclusion
  - field: country
    operator: not_in
    values: ["Other"]

  # Range
  - field: revenue
    operator: between
    range: [1000, 5000]
```

**Operator → value field rules** (strictly enforced):

| Operator | Required field | Forbidden fields |
|---|---|---|
| `in`, `not_in` | `values` (list) | `value`, `range` |
| `between` | `range` (2-element list) | `value`, `values` |
| `eq`, `neq`, `gt`, `lt`, `gte`, `lte` | `value` (scalar) | `values`, `range` |

---

## Sort

Sort modifies the encoding on a target channel (defaults to `x`).

```yaml
# Sort x-axis by a field's values
sort:
  field: revenue
  order: descending

# Sort x-axis by y-axis values
sort:
  axis: y
  order: ascending

# Custom order
sort:
  field: country
  order: ["US", "UK", "DE", "FR"]

# Target a different channel
sort:
  field: revenue
  order: descending
  channel: y
```

---

## Facet

Partition a chart into small multiples.

### Row/column facet

```yaml
facet:
  row: region                # facet into rows by region
  axis: independent          # independent | shared (axis scales)
```

```yaml
facet:
  column: category           # facet into columns
```

```yaml
facet:
  row: region
  column: category           # grid facet
```

At least one of `row` or `column` is required.

### Wrap facet

```yaml
facet:
  field: country
  columns: 4                 # wrap into 4 columns
  sort: descending           # optional sort order
  axis: independent          # optional axis scale resolution
```

---

## Axis configuration

Customize axis appearance for single-measure charts:

```yaml
axis:
  x:
    title: "Country"
    format: "%b %Y"
    grid: false
  y:
    title: "Revenue ($)"
    format: "$,.0f"
    grid: true
```

### Auto-injection from model

When a chart references a data model (`data: orders`), the translator automatically injects:

- **Axis titles** from the model's field `label` (e.g. `revenue` → title "Revenue")
- **Axis formats** from the model's `format` string (e.g. `"$,.0f"` for revenue)
- **Temporal formats** from the model's per-grain format map (e.g. `"%b %Y"` for month grain)
- **Grid defaults**: y-axis grid on, x-axis grid off
- **Legend titles** from the model's dimension `label`
- **Tooltip labels and formats** from the model's field `label` and `format`
- **Default sort** from the model's `defaultSort` (measure) or `sortOrder` (dimension)

All auto-injected values can be overridden by explicit chart-level configuration. The precedence order:

1. Explicit chart config (e.g. `axis.y.title`, `sort:`) — **always wins**
2. Model field metadata (label, format, defaultSort, sortOrder)

```yaml
# No axis config needed — model provides titles, formats, and grid defaults
sheet: "Revenue by Country"
data: orders
cols: country
rows: revenue
marks: bar
color: country
tooltip: [country, revenue]
```

---

## Title and subtitle

Every chart automatically renders its `sheet` name as the Vega-Lite title. The optional `description` field renders as the subtitle:

```yaml
sheet: "Revenue by Country"
description: "Weekly aggregate revenue across all product lines"
data: orders
cols: country
rows: revenue
marks: bar
```

The title appears above the chart in Vega-Lite's default title position. Both single-measure and multi-measure charts support titles.

### Suppressing titles in dashboards

In dashboards, set `show_title: false` on a sheet component to hide the chart title (useful when the dashboard provides its own section headings):

```yaml
- sheet: revenue.yaml
  show_title: false
```

When `show_title` is `true` (the default), the chart title renders normally.

---

## Theme

Shelves uses a `theme.yaml` file to control visual styling across all charts and dashboards. The theme has two sections:

- **`chart`** — Vega-Lite config properties (colors, fonts, padding, mark defaults). Applied to every chart via `spec.config`.
- **`layout`** — Tokens for the Layout DSL (text presets, surface colors, typography). Used by dashboard rendering.

### Using the default theme

By default, Shelves applies its built-in theme. No configuration needed:

```bash
shelves-render my_chart.yaml --data data.json
```

### Using a custom theme

Create a `theme.yaml` file and pass it via `--theme`:

```bash
shelves-render my_chart.yaml --data data.json --theme my_theme.yaml
```

### Theme file structure

```yaml
chart:
  background: "#ffffff"
  mark:
    color: "#4A90D9"
  axis:
    labelFont: "Inter, system-ui, sans-serif"
    labelFontSize: 11
    titleFont: "Inter, system-ui, sans-serif"
    titleFontSize: 12
    gridColor: "#f0f0f0"
  range:
    category: ["#4A90D9", "#E5A84B", "#5BBD72", "#D94A6B"]
  bar:
    cornerRadius: 2
  padding: 16

layout:
  text:
    primary: "#1a1a1a"
    secondary: "#666666"
    tertiary: "#999999"
  font:
    family:
      body: "Inter, system-ui, sans-serif"
      heading: "Inter, system-ui, sans-serif"
  surface: "#ffffff"
  background: "#f5f5f5"
  border: "#e5e7eb"
  presets:
    title:
      font_size: 24
      font_weight: bold
      color: text.primary
    body:
      font_size: 14
      font_weight: normal
      color: text.primary
```

### Partial overrides

You only need to include the keys you want to change. Unspecified keys use the built-in defaults. For example, to change just the brand color palette:

```yaml
chart:
  mark:
    color: "#e94560"
  range:
    category: ["#e94560", "#0f3460", "#16213e", "#533483"]

layout:
  text:
    primary: "#ffffff"
  surface: "#1a1a2e"
  background: "#0f0f1a"
```

### Preset color references

In the `layout.presets` section, the `color` field supports references to `layout.text` values:

- `text.primary` → resolves to `layout.text.primary`
- `text.secondary` → resolves to `layout.text.secondary`
- `text.tertiary` → resolves to `layout.text.tertiary`

You can also use hex values directly: `color: "#ff0000"`.

### Skipping the theme

To render without any theme applied:

```bash
shelves-render my_chart.yaml --data data.json --no-theme
```

---

## Complete examples

### Simple bar chart

```yaml
sheet: "Revenue by Country"
data: orders
cols: country
rows: revenue
marks: bar
color: country
sort:
  field: revenue
  order: descending
tooltip: [country, revenue]
```

### Line chart with time

```yaml
sheet: "Weekly Revenue Trend"
data: orders
cols: week
rows: revenue
marks: line
tooltip: [week, revenue]
```

### Scatter plot

```yaml
sheet: "Revenue vs Order Count"
data: orders
cols: revenue
rows: order_count
marks: circle
color: country
size: revenue
tooltip: [country, revenue, order_count]
```

### Heatmap

```yaml
sheet: "Revenue Heatmap"
data: orders
cols: product
rows: country
marks: rect
color:
  field: revenue
  type: quantitative
tooltip: [country, product, revenue]
```

### Multi-measure stacked panels (same mark)

```yaml
sheet: "Key Metrics by Week"
data: orders
cols: week
marks: line
rows:
  - measure: revenue
  - measure: order_count
  - measure: arpu
tooltip: [week]
```

### Multi-measure stacked panels (different marks)

```yaml
sheet: "Revenue and Orders"
data: orders
cols: week
rows:
  - measure: revenue
    mark: bar
    color: country
  - measure: order_count
    mark: line
    color: country
tooltip: [week, country]
```

### Dual axis (layers with independent scales)

```yaml
sheet: "Revenue & ARPU by Week"
data: orders
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

Revenue bars colored by country, with an ARPU dashed line overlaid on independent y-axes.

### Layered chart with shared axis

```yaml
sheet: "Revenue vs Cost"
data: orders
cols: week
rows:
  - measure: revenue
    mark: line
    color: "#4A90D9"
    layer:
      - measure: cost
        mark:
          type: line
          style: dashed
        color: "#cccccc"
tooltip: [week, revenue, cost]
```

Two measures on a shared y-axis — no `axis: independent` needed since both are dollar values.

### Model-based chart with dot notation

```yaml
sheet: "Monthly Revenue Trend"
data: orders
cols: week.month
rows: revenue
marks: line
color: country
tooltip: [week.month, country, revenue]
```

Uses the `orders` data model for field definitions. `week.month` applies the month grain to the `week` temporal dimension. Labels, formats, and sort defaults come from the model automatically.

### Faceted chart

```yaml
sheet: "Revenue Trend by Country"
data: orders
cols: month
rows: revenue
marks: line
tooltip: [month, country, revenue]
facet:
  field: country
  columns: 4
  sort: descending
```

---

## Dashboards (Layout DSL)

Shelves also supports a Layout DSL for composing multi-chart dashboards. Dashboard YAML files use a different top-level structure (`dashboard`, `canvas`, `root` instead of `sheet`, `cols`, `rows`).

See the **[Dashboards guide](./dashboards.md)** for the complete Layout DSL reference.

---

## Not yet supported

The following features are parsed and validated by the schema but **will raise `NotImplementedError` at compilation time**. They are planned for upcoming releases.

### KPI cards

```yaml
kpi:
  measure: revenue
  format: "$,.0f"
  comparison:
    measure: revenue_prior_period
    type: percent_change
    format: "+.1%"
```

**Status:** Schema validates. No translator support yet.

---

## DSL version history

| Version | Status | Summary |
|---|---|---|
| **0.5.0** | Current | Layer compilation (dual/triple axis): single-entry `layer` specs compile to Vega-Lite `layer` arrays with encoding inheritance, opacity merging, and axis scale resolution. Multi-entry layered shelves remain deferred. |
| **0.4.0** | Previous | Unified `theme.yaml` with `chart` + `layout` sections, `--theme` CLI flag, partial theme overrides. |
| **0.3.0** | Previous | **Breaking:** removed legacy `DataSource` inline declaration. `data` is now always a model name string. |
| **0.2.0** | Previous | Data model shorthand (`data: orders`), temporal dot notation (`cols: order_date.month`), auto-injected axis formats from model. |
| **0.1.0** | — | Single-measure charts, multi-measure stacked panels (repeat/concat), filters, sort, facet, themes, data binding, HTML rendering. Layers and KPI parsed but not compiled. |
