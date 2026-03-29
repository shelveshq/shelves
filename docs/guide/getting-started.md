# Getting Started

## Installation

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
```

## Rendering a chart

Write a YAML file following the [DSL Reference](./dsl-reference.md), then render it to HTML:

```bash
# Render without data (produces a Vega-Lite spec with no data values)
charter-render path/to/chart.yaml

# Render with inline JSON data
charter-render path/to/chart.yaml --data path/to/data.json

# Custom output path
charter-render path/to/chart.yaml --out output/my-chart.html

# Skip default theme
charter-render path/to/chart.yaml --no-theme
```

### Custom theme

Pass a custom theme file to change colors, fonts, and spacing:

```bash
python -m src.cli.render my_chart.yaml --data data.json --theme my_theme.yaml
```

See [Theme](dsl-reference.md#theme) in the DSL reference for the full theme file format.

The data file should be a JSON array of row objects:

```json
[
  {"country": "US", "revenue": 5000, "week": "2024-01-01"},
  {"country": "UK", "revenue": 3200, "week": "2024-01-01"}
]
```

Output defaults to `output/<sheet-name-slug>.html`.

## Using data models

Instead of declaring measures and dimensions in every chart, define them once in a model file:

```yaml
# models/orders.yaml
model: orders
label: Orders
measures:
  revenue:
    label: Revenue
    format: "$,.0f"
dimensions:
  country:
    label: Country
  week:
    type: temporal
    label: Week
    defaultGrain: week
```

Then reference the model by name in your chart:

```yaml
sheet: "Revenue by Country"
data: orders
cols: country
rows: revenue
marks: bar
```

## Rendering a dashboard

Dashboards compose multiple charts into a single HTML page with layout, text, navigation, and styling. Write a dashboard YAML file that references your chart files:

```yaml
# dashboards/sales_overview.yaml
dashboard: "Sales Overview"
canvas: { width: 1440, height: 900 }

root:
  type: root
  orientation: vertical
  contains:
    - type: text
      content: "Sales Overview"
      preset: title
      padding: "16 24"
    - charts:
        type: container
        orientation: horizontal
        padding: "0 24"
        contains:
          - revenue: { type: sheet, link: "charts/revenue.yaml", width: "60%" }
          - orders: { type: sheet, link: "charts/orders.yaml", width: "40%" }
```

Then render it:

```bash
python -m src.cli.render dashboards/sales_overview.yaml
```

See the [Dashboards guide](./dashboards.md) for the full Layout DSL reference, component types, styling, and complete examples.

## Python API

```python
from pathlib import Path
from src import parse_chart, translate_chart, merge_theme, bind_data, render_html

yaml_string = Path("chart.yaml").read_text()

spec   = parse_chart(yaml_string)       # validate YAML → ChartSpec
vl     = translate_chart(spec)          # compile → Vega-Lite dict
themed = merge_theme(vl)               # apply default theme
bound  = bind_data(themed, rows)       # attach data rows
html   = render_html(bound)            # standalone HTML with vegaEmbed
```

Each step is independent and composable. You can skip `merge_theme` or `bind_data` if you don't need them.

## Running tests

```bash
pytest                # all tests
pytest -v             # verbose
pytest tests/test_translator.py::TestSingleMarkCharts::test_simple_bar  # single test
```

## Linting

```bash
ruff check src tests
ruff format src tests
```
