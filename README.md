# Shelves

Declarative visual analytics for semantic models. Write charts and dashboards in YAML, render to Vega-Lite.

Shelves connects to your [Cube.dev](https://cube.dev) semantic layer, so your charts inherit consistent definitions for measures, dimensions, formats, and aggregations — no copy-pasting field logic across dashboards.

> More connectors are planned. For now, Shelves requires a Cube.dev instance as its data backend.

## Install

```bash
pip install shelves-bi
```

Requires Python 3.11+.

## Project structure

A typical Shelves project looks like this:

```
my-project/
  models/
    orders.yaml          # semantic model definitions
  charts/
    revenue_by_country.yaml
    sales_over_time.yaml
  dashboards/
    overview.yaml
  .env                   # CUBE_API_URL and CUBE_API_TOKEN
```

## Connect to Cube

Set your Cube.dev credentials in a `.env` file or as environment variables:

```bash
CUBE_API_URL=http://localhost:4000
CUBE_API_TOKEN=your-cube-api-token
```

## Define a model

Models map your Cube cubes to the measures and dimensions your charts can use:

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

## Write a chart

Charts reference a model by name. Measures, dimensions, formats, and sort orders are resolved from the model:

```yaml
# charts/sales_by_category.yaml
sheet: "Net Sales by Category"
data: orders

cols: category
rows: net_sales
marks: bar
color: category
sort:
  field: net_sales
  order: descending
```

## Render

```bash
# Single chart
shelves-render charts/sales_by_category.yaml --models-dir models/

# Dashboard (charts and models resolved from directories)
shelves-render dashboards/overview.yaml --chart-dir charts/ --models-dir models/

# Dev server with live reload
shelves-dev charts/sales_by_category.yaml --models-dir models/
```

Output goes to `output/<sheet-name-slug>.html` by default. Use `--out` to override.

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
          - sheet: "charts/sales_by_category.yaml"
            width: "60%"
          - sheet: "charts/sales_over_time.yaml"
            width: "40%"
```

## Python API

```python
from shelves import parse_chart, translate_chart, merge_theme, render_html
from shelves.data.bind import resolve_data

spec   = parse_chart(yaml_string)          # YAML -> ChartSpec
vl     = translate_chart(spec)             # ChartSpec -> Vega-Lite dict
themed = merge_theme(vl)                   # apply default theme
final  = resolve_data(themed, spec)        # fetch from Cube and bind
html   = render_html(final)                # standalone HTML with vegaEmbed
```

Each step is independent and composable.

## Documentation

- [Getting Started](docs/guide/getting-started.md) — setup, first chart, first dashboard
- [DSL Reference](docs/guide/dsl-reference.md) — complete field and property reference
- [Dashboards](docs/guide/dashboards.md) — layout DSL, components, and styling

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
