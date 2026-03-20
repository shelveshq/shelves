# Charter DSL Reference

**DSL Version: 0.2.0**

This document is the authoritative reference for the Charter YAML DSL. It covers every field, what is currently supported, and what is planned but not yet compiled.

## Spec structure

Every chart YAML file is a single document with this top-level shape:

```yaml
version: "0.1.0"          # optional — DSL version this spec targets
sheet: "My Chart Title"    # required — chart name
description: "..."         # optional

data:
  model: orders            # semantic model name
  measures: [revenue]      # quantitative fields
  dimensions: [country]    # categorical/nominal fields
  time_grain:              # optional — marks a dimension as temporal
    field: week
    grain: week            # day | week | month | quarter | year

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

### Model shorthand (recommended)

```yaml
data: orders
```

When `data` is a string, it references a data model file (`models/orders.yaml`). The model defines all measures, dimensions, field types, labels, and formats. No need to redeclare them in every chart.

### Verbose form (legacy)

```yaml
data:
  model: orders
  measures: [revenue, order_count, arpu]
  dimensions: [country, week, region]
  time_grain:
    field: week
    grain: week
```

The verbose form still works. Use it when you don't have a model file or need to override field declarations.

- **model** — name of the semantic data model.
- **measures** — fields treated as quantitative (numbers).
- **dimensions** — fields treated as nominal (categories).
- **time_grain** — marks one dimension as temporal.

Field type resolution: measures → `quantitative`, dimensions → `nominal`, `time_grain.field` → `temporal`.

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

---

## Complete examples

### Simple bar chart

```yaml
sheet: "Revenue by Country"
data:
  model: orders
  measures: [revenue]
  dimensions: [country]

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
data:
  model: orders
  measures: [revenue]
  dimensions: [week]
  time_grain:
    field: week
    grain: week

cols: week
rows: revenue
marks: line
tooltip: [week, revenue]
```

### Scatter plot

```yaml
sheet: "Revenue vs Order Count"
data:
  model: orders
  measures: [revenue, order_count]
  dimensions: [country]

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
data:
  model: orders
  measures: [revenue]
  dimensions: [country, product]

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
data:
  model: orders
  measures: [revenue, order_count, arpu]
  dimensions: [week]
  time_grain:
    field: week
    grain: week

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
data:
  model: orders
  measures: [revenue, order_count]
  dimensions: [country, week]
  time_grain:
    field: week
    grain: week

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

### Model-based chart (data shorthand)

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
data:
  model: orders
  measures: [revenue]
  dimensions: [country, month]
  time_grain:
    field: month
    grain: month

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

## Not yet supported

The following features are parsed and validated by the schema but **will raise `NotImplementedError` at compilation time**. They are planned for upcoming releases.

### Layers (dual/multi-axis)

Layers overlay multiple measures in the same chart panel with independent or shared axis scales:

```yaml
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

**Status:** Schema validates. Translator raises `NotImplementedError`.

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
| **0.2.0** | Current | Data model shorthand (`data: orders`), temporal dot notation (`cols: order_date.month`), auto-injected axis formats from model. |
| **0.1.0** | Previous | Single-measure charts, multi-measure stacked panels (repeat/concat), filters, sort, facet, themes, data binding, HTML rendering. Layers and KPI parsed but not compiled. |
