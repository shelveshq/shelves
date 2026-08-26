# Shelves grammar card

The complete Shelves DSL for writing charts and dashboards. **Fields (measures
and dimensions) come from the semantic model — call `get_model` first and use
only the names it returns; never invent field names.** `data:` names the model.
Examples below use a model named `orders`.

## Chart skeleton

Every chart needs `sheet:` (title) and `data:` (model). Put a dimension on one
of `cols`/`rows`, a measure on the other, and choose `marks`.

```yaml
sheet: "Revenue by Country"
data: orders
cols: country      # dimension
rows: revenue      # measure
marks: bar
```

## Marks (closed set)

`bar` `line` `area` `circle` `square` `point` `tick` `rect` `arc` `text`
`rule` `geoshape`. A mark can also be an object:
`mark: {type: line, style: dashed, point: true, opacity: 0.8}` (styles:
`solid`, `dashed`, `dotted`).

## Encoding channels

- `color` — a dimension (categorical), a fixed hex like `"#666666"`, or
  `{field: revenue, type: quantitative}` for a continuous scale
- `detail` — disaggregate without a visual channel (`detail: null` on a layer
  suppresses inherited detail, e.g. an aggregate reference line)
- `size` — a measure or a fixed number of pixels
- `tooltip` — a list of fields, or `{field, format}` entries
- `sort`, `label`, `axis` — see below

Optional top-level text: `description` renders as the subtitle.

## Patterns (one example each)

Grouped / stacked bar — add `color` (a dimension):

```yaml
sheet: "Revenue by Country and Product"
data: orders
cols: country
rows: revenue
marks: bar
color: product
```

Line / multi-line — temporal dimension on `cols`, `color` splits series:

```yaml
sheet: "Weekly Revenue by Country"
data: orders
cols: week
rows: revenue
marks: line
color: country
```

Scatter — a measure on both axes:

```yaml
sheet: "Revenue vs Orders"
data: orders
cols: revenue
rows: order_count
marks: circle
color: country
size: revenue
```

Heatmap — two dimensions, measure on `color`:

```yaml
sheet: "Revenue Heatmap"
data: orders
cols: product
rows: country
marks: rect
color:
  field: revenue
  type: quantitative
```

KPI — a single formatted value (omit cols/rows/marks). Optional `comparison`
adds a delta line; `mode` is `delta_percent` (default), `delta_absolute`, or
`value`; `polarity` is `up_is_good` (default), `down_is_good`, or `neutral`:

```yaml
sheet: "Total Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  title: "Monthly Revenue"
  comparison:
    field: cost
    mode: delta_percent
    label: "vs. Cost"
    polarity: up_is_good
```

## Multi-measure stacked panels

A list on exactly ONE shelf (`rows` or `cols`, never both) stacks one panel per
measure and shares the other axis. Each entry may set its own `mark`/`color`.

```yaml
sheet: "Key Metrics by Week"
data: orders
cols: week
marks: line
rows:
  - measure: revenue
  - measure: order_count
  - measure: arpu
```

## Layers (dual / multi-axis)

`layer:` overlays measures in the same space. `axis: independent` gives each
measure its own scale; `shared` puts them on one.

```yaml
sheet: "Revenue & ARPU by Week"
data: orders
cols: week
rows:
  - measure: revenue
    mark: bar
    layer:
      - measure: arpu
        mark: {type: line, style: dashed}
        color: "#666666"
    axis: independent
```

## Facet (small multiples)

Repeat the chart per dimension value: `facet.row`, `facet.column`, or
`facet.field` with `facet.columns: N` to wrap.

```yaml
sheet: "Revenue by Country, by Region"
data: orders
cols: country
rows: revenue
marks: bar
facet:
  row: region
  axis: independent
```

## Filters

`filters:` is a list. The operator decides which value key to use:

| operators | value key |
|-----------|-----------|
| `eq` `neq` `gt` `lt` `gte` `lte` `contains` | `value` (scalar) |
| `in` `not_in` | `values` (list) |
| `between` | `range` ([min, max]) |

```yaml
sheet: "EMEA Revenue by Country"
data: orders
cols: country
rows: revenue
marks: bar
filters:
  - field: region
    operator: in
    values: ["EMEA", "APAC"]
  - field: week
    operator: between
    range: ["2024-01-01", "2024-03-31"]
```

## Sort

`sort:` a shelf by a field. `order:` is `ascending`, `descending`, or an
explicit list of values.

```yaml
sheet: "Revenue by Country"
data: orders
cols: country
rows: revenue
marks: bar
sort:
  field: revenue
  order: descending
```

## Labels

`label: true` writes the value on each mark; the field, format, and position
come from the model. Or configure it (position is on the mark's measure axis —
`vertical` for vertical bars, `horizontal` for horizontal). `center` places the
value inside the mark, the natural choice for stacked segments. `color: match`
paints the label the mark's color; omit `color` for automatic contrast.
Supported on `bar`, `point`/`circle`/`square`, `tick`, `rect` (heatmap);
ignored on `line`/`area`/`arc`. `label: false` suppresses an inherited label.

```yaml
sheet: "Revenue by Country"
data: orders
cols: country
rows: revenue
marks: bar
label:
  field: revenue
  vertical: top
  format: "$,.0f"
```

## Axis

`axis.x` / `axis.y` customize an axis. Each takes toggles (`title`, `format`,
`grid`, `ruler`, `ticks`, `labels`) or a bare bool — `x: false` removes the
axis entirely. Omitted toggles inherit the theme; titles/formats otherwise come
from the model.

```yaml
sheet: "Weekly Revenue"
data: orders
cols: week
rows: revenue
marks: line
axis:
  x:
    title: "Week"
    grid: false
  y:
    format: "$,.0f"
    grid: true
```

## Inheritance (top-level → entry → layer)

Top-level `marks`/`color`/`detail`/`size` are defaults. A measure entry
overrides them; a layer entry overrides the entry. More specific always wins.

```text
marks: line            # default
color: country         # default
  rows[0].mark: bar        # entry overrides the mark
  rows[0].color            # unset -> inherits "country"
    layer[0].mark: line    # layer overrides
    layer[0].color: "#666" # layer overrides
```

## Temporal grains

A temporal dimension has a default grain; write `field.grain` for another
(grains: `day`, `week`, `month`, `quarter`, `year`) — e.g. `cols: week.month`.

## Parameters

Runtime knobs declared once per project (in `models/parameters.yaml`, never in
a chart) and referenced by name. Four types: `field` (a measure/dimension
swapper), `string`, `number`, `date`. Call `list_parameters` for the declared
set. Reference a whole value with `$name` — in a field slot (`rows`, `color`,
a filter's `field`, …) for `field` params, or in a filter value for the others.
Embed one in text (`sheet`, titles) with `${name}`. `$$` is a literal `$`.

```yaml
sheet: "${metric} by Country"
data: orders
cols: country
rows: $metric
marks: bar
filters:
  - field: region
    operator: eq
    value: $region
```

## Theme

Visual styling — fonts, color palette, mark defaults, axis line styling, layout
tokens — lives in a separate `theme.yaml` (not in a spec) and is applied with
`--theme`. A spec never carries a `theme:` key. In a spec you control only
appearance that is data-bound: per-mark `style`/`opacity`/`point`, fixed hex
colors, and axis visibility toggles. See the DSL reference for the theme grammar.

## Dashboards

A dashboard composes chart `sheet` files into a layout tree under a `dashboard:`
root. Fetch the dashboard grammar from `shelves://schema/dashboard`.
