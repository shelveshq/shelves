# Getting Started

Shelves charts read from a **semantic model** — a reusable YAML file that defines your measures, dimensions, labels, and formats. A model can be backed two ways:

- **A flat file** (CSV, Parquet, or JSON), queried locally with [DuckDB](https://duckdb.org). No infrastructure — the fastest way to a first chart.
- **A [Cube.dev](https://cube.dev) semantic layer**, for shared governed definitions across a team.

Both paths use the same model and chart schema. Start with a file and graduate to Cube later by changing only the model's `source` block — your charts stay untouched.

## Installation

Requires Python 3.11+.

```bash
pip install shelves-bi
```

For the flat-file path (CSV/Parquet/JSON via DuckDB), install the optional extra:

```bash
pip install 'shelves-bi[duckdb]'
```

## Path A — Start with a flat file

### Import a file

Generate a model from a CSV instead of writing one by hand:

```bash
shelves-import sales.csv
```

This creates `models/sales.yaml` with dimensions and measures auto-inferred from the file schema:
- String columns → dimensions
- Numeric columns → measures (with `sum` aggregation)
- Date/datetime columns → temporal dimensions
- Boolean columns → dimensions

The generated model points at your file and is a starting point — edit it to add formats, change aggregation types, remove irrelevant fields, or add calculated measures:

```yaml
# models/sales.yaml
model: sales
label: Sales

source:
  type: file
  path: sales.csv

measures:
  revenue:
    column: Revenue
    aggregation: sum
    label: Revenue
    format: "$,.0f"

dimensions:
  category:
    column: Category
    label: Category
  order_date:
    column: Order Date
    type: temporal
    label: Order Date
    defaultGrain: month
```

#### Options

```bash
# Custom model name
shelves-import sales.csv --name orders

# Custom output directory
shelves-import sales.csv --models-dir path/to/models/

# Overwrite existing model
shelves-import sales.csv --overwrite
```

Parquet and JSON files are also supported:

```bash
shelves-import data.parquet
shelves-import records.json
```

## Path B — Connect to Cube

When you want a governed semantic layer, point the model's `source` at a [Cube.dev](https://cube.dev) instance instead. Set your credentials in a `.env` file or as environment variables:

```bash
CUBE_API_URL=http://localhost:4000
CUBE_API_TOKEN=your-cube-api-token
```

The model maps your Cube cubes to the measures and dimensions your charts can use. Only the `source` block differs from a file model — everything else is declared the same way:

```yaml
# models/orders.yaml
model: orders
label: Orders

source:
  type: cube
  cube: orders

measures:
  revenue:
    label: Revenue
    format: "$,.0f"
    aggregation: sum
dimensions:
  country:
    label: Country
  week:
    type: temporal
    label: Week
    defaultGrain: week
    format:
      week: "%b %d"
      month: "%b %Y"
```

## Write a chart

Charts reference a model by name. Measures, dimensions, formats, and sort orders are all resolved from the model:

```yaml
# charts/revenue_by_country.yaml
sheet: "Revenue by Country"
data: orders
cols: country
rows: revenue
marks: bar
color: country
sort:
  field: revenue
  order: descending
```

## Render

```bash
# Single chart
shelves-render charts/revenue_by_country.yaml --models-dir models/

# Custom output path
shelves-render charts/revenue_by_country.yaml --models-dir models/ --out output/chart.html

# Skip default theme
shelves-render charts/revenue_by_country.yaml --models-dir models/ --no-theme

# Custom theme
shelves-render charts/revenue_by_country.yaml --models-dir models/ --theme my_theme.yaml
```

See [Theme](dsl-reference.md#theme) in the DSL reference for the full theme file format.

Output defaults to `output/<sheet-name-slug>.html`.

## Dashboards

Dashboards compose multiple charts into a single HTML page with layout, text, navigation, and styling:

```yaml
# dashboards/sales_overview.yaml
dashboard: "Sales Overview"
canvas: { width: 1440, height: 900 }

root:
  orientation: vertical
  contains:
    - text: "Sales Overview"
      preset: title
      padding: "16 24"
    - horizontal:
        padding: "0 24"
        contains:
          - sheet: "charts/revenue.yaml"
            width: "60%"
          - sheet: "charts/orders.yaml"
            width: "40%"
```

```bash
shelves-render dashboards/sales_overview.yaml --chart-dir charts/ --models-dir models/
```

Each chart resolves its own data from its model's configured source. See the [Dashboards guide](./dashboards.md) for the full Layout DSL reference.

## Parameters

A parameter is a named value declared once for the project and referenced from
any chart with `$name`. Put them in `models/parameters.yaml`, beside your model
manifests:

```yaml
# models/parameters.yaml
parameters:
  metric:
    type: field
    values:
      - model: orders
        field: revenue
      - model: orders
        field: cost
    default: revenue
    label: Metric
```

Reference it from a chart:

```yaml
# charts/metric_by_country.yaml
sheet: "Metric by Country"
data: orders

cols: country
rows: $metric
marks: bar
```

Render it with the default, then with an override:

```bash
shelves-render charts/metric_by_country.yaml --models-dir models/
shelves-render charts/metric_by_country.yaml --models-dir models/ --param metric=cost
```

`--param` works the same way on `shelves-dev`, and on dashboards — the value
applies to every sheet:

```bash
shelves-render dashboards/sales.yaml --chart-dir charts/ --models-dir models/ --param metric=cost
```

Parameters can also appear inside `calculation` fields in model manifests
(file-backed sources only), letting a single calculated measure serve multiple
granularities. See [Parameterized calculations](dsl-reference.md#parameterized-calculations).

If your parameters file lives somewhere other than `models/parameters.yaml`,
point at it with `--parameters-file`. See the
[DSL reference](dsl-reference.md#parameters) for the full declaration grammar
and the list of positions where `$name` may appear.

To make a parameter interactive in a dashboard, add a `parameter:` element:

```yaml
# dashboards/sales.yaml
dashboard: "Sales Dashboard"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - horizontal:
        gap: 16
        height: 48
        contains:
          - parameter: metric
    - sheet: metric_by_country.yaml
      name: chart
      height: "90%"
```

In Shelves Studio, the parameter renders as a dropdown (inferred from `type: field`).
Changing the selection recompiles the dashboard with the new value. In exported
HTML, the parameter renders disabled — parameters are baked in at compile time.

See the [Dashboards guide](dashboards.md#parameter-widget) for widget
inference rules and all parameter component properties.

## Dev server

Live reload while editing charts:

```bash
shelves-dev charts/revenue_by_country.yaml --models-dir models/
```

Opens at http://localhost:8089 and refreshes on YAML changes.

## Python API

```python
from shelves import parse_chart, translate_chart, merge_theme, render_html
from shelves.data.bind import resolve_data

spec   = parse_chart(yaml_string)          # YAML → ChartSpec
vl     = translate_chart(spec)             # ChartSpec → Vega-Lite dict
themed = merge_theme(vl)                   # apply default theme
final  = resolve_data(themed, spec)        # fetch from Cube and bind
html   = render_html(final)                # standalone HTML with vegaEmbed
```

Each step is independent and composable. You can skip `merge_theme` or `resolve_data` if you don't need them.

## Development

```bash
git clone https://github.com/shelveshq/shelves.git
cd shelves
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
