# Getting Started

## Installation

Requires Python 3.11+.

```bash
pip install shelves-bi
```

## Connect to Cube

Shelves connects to [Cube.dev](https://cube.dev) for data. Set your credentials in a `.env` file or as environment variables:

```bash
CUBE_API_URL=http://localhost:4000
CUBE_API_TOKEN=your-cube-api-token
```

## Define a model

Models map your Cube cubes to the measures and dimensions your charts can use. Define them once, reference from any chart:

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
