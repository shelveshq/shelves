<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/shelveshq/shelves/main/assets/lockup-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/shelveshq/shelves/main/assets/lockup.svg">
    <img src="https://raw.githubusercontent.com/shelveshq/shelves/main/assets/lockup.svg" alt="shelves" width="280">
  </picture>
</p>

<p align="center">
  Declarative visual analytics for semantic models.<br>
  Write charts and dashboards in YAML, render to Vega-Lite.
</p>

Shelves charts read from a **semantic model** — measures, dimensions, formats, and aggregations defined once and reused everywhere, so you never copy-paste field logic across dashboards. You can back that model two ways:

- **Start with a flat file.** Point a model at a local CSV, Parquet, or JSON file and Shelves queries it directly with [DuckDB](https://duckdb.org). `shelves-import` can even generate the model for you. Zero infrastructure — go from a raw file to a chart in seconds.
- **Grow into a semantic layer.** Point the same model at a [Cube.dev](https://cube.dev) instance when you want shared governed definitions across a team. Only the model's `source` block changes; your charts stay untouched.

The two paths use the identical model and chart schema, so a project can graduate from file to Cube without rewriting a single chart.

## Install

```bash
pip install shelves-bi
```

For the flat-file path, install the optional DuckDB extra:

```bash
pip install 'shelves-bi[duckdb]'
```

Requires Python 3.11+.

## Quick start (flat file)

Generate a model from a CSV — string columns become dimensions, numeric columns become measures, dates become temporal dimensions:

```bash
shelves-import sales.csv          # writes models/sales.yaml
```

The generated model points at your file:

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

Write a chart that references the model by name, then render:

```yaml
# charts/revenue_by_category.yaml
sheet: "Revenue by Category"
data: sales

cols: category
rows: revenue
marks: bar
color: category
sort:
  field: revenue
  order: descending
```

```bash
shelves-render charts/revenue_by_category.yaml --models-dir models/
```

Output goes to `output/<sheet-name-slug>.html` by default. Use `--out` to override.

## Connect to Cube

When you're ready for a governed semantic layer, point the model's `source` at a Cube.dev instance instead. Set your credentials in a `.env` file or as environment variables:

```bash
CUBE_API_URL=http://localhost:4000
CUBE_API_TOKEN=your-cube-api-token
```

Only the `source` block changes — measures, dimensions, labels, and formats are declared the same way as the file model above:

```yaml
# models/orders.yaml
model: orders
label: Orders

source:
  type: cube
  cube: orders

measures:
  net_sales:
    label: Net Sales
    format: "$,.0f"
    aggregation: sum

dimensions:
  category:
    label: Category
  order_date:
    type: temporal
    label: Order Date
    defaultGrain: month
    format:
      month: "%b %Y"
```

Your existing charts keep working unchanged.

## Project structure

A typical Shelves project looks like this:

```
my-project/
  models/
    sales.yaml           # semantic model definitions (file or cube source)
  charts/
    revenue_by_category.yaml
    sales_over_time.yaml
  dashboards/
    overview.yaml
  .env                   # CUBE_API_URL / CUBE_API_TOKEN (only for the Cube path)
```

## Dashboards

Dashboards compose multiple charts into a single HTML page with layout, text, and styling:

```yaml
# dashboards/overview.yaml
dashboard: "Sales Overview"
canvas: { width: 1440, height: 900 }

root:
  orientation: vertical
  contains:
    - text: "Sales Overview"
      preset: title
    - horizontal:
        contains:
          - sheet: "charts/revenue_by_category.yaml"
            width: "60%"
          - sheet: "charts/sales_over_time.yaml"
            width: "40%"
```

```bash
# Dashboard (charts and models resolved from directories)
shelves-render dashboards/overview.yaml --chart-dir charts/ --models-dir models/

# Dev server with live reload
shelves-dev charts/revenue_by_category.yaml --models-dir models/
```

## Python API

```python
from shelves import parse_chart, translate_chart, merge_theme, render_html
from shelves.data.bind import resolve_data

spec   = parse_chart(yaml_string)          # YAML -> ChartSpec
vl     = translate_chart(spec)             # ChartSpec -> Vega-Lite dict
themed = merge_theme(vl)                   # apply default theme
final  = resolve_data(themed, spec)        # query the model's source and bind
html   = render_html(final)                # standalone HTML with vegaEmbed
```

Each step is independent and composable.

## Documentation

- [Getting Started](https://github.com/shelveshq/shelves/blob/main/docs/guide/getting-started.md) — setup, first chart, first dashboard
- [DSL Reference](https://github.com/shelveshq/shelves/blob/main/docs/guide/dsl-reference.md) — complete field and property reference
- [Dashboards](https://github.com/shelveshq/shelves/blob/main/docs/guide/dashboards.md) — layout DSL, components, and styling

## Development

```bash
git clone https://github.com/shelveshq/shelves.git
cd shelves
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## License

Apache 2.0
