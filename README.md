<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/shelveshq/shelves/main/assets/lockup-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/shelveshq/shelves/main/assets/lockup.svg">
    <img src="https://raw.githubusercontent.com/shelveshq/shelves/main/assets/lockup.svg" alt="shelves" width="280">
  </picture>
</p>

<p align="center">
  <strong>The git-native chart grammar that lets your AI agent build governed dashboards on your semantic layer.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/shelves-bi/"><img src="https://img.shields.io/pypi/v/shelves-bi?style=flat-square&color=B8531C&label=pypi" alt="PyPI version"></a>
  <a href="https://pypi.org/project/shelves-bi/"><img src="https://img.shields.io/pypi/pyversions/shelves-bi?style=flat-square&color=0B0B0A" alt="Supported Python versions"></a>
  <a href="https://github.com/shelveshq/shelves/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/shelveshq/shelves/ci.yml?branch=main&style=flat-square&label=ci" alt="CI status"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&style=flat-square" alt="Linted with Ruff"></a>
  <a href="https://github.com/microsoft/pyright"><img src="https://img.shields.io/badge/types-pyright-0B0B0A?style=flat-square" alt="Checked with pyright"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-0B0B0A?style=flat-square" alt="License: Apache 2.0"></a>
</p>

Shelves compiles a Tableau-style shelf grammar — rows, columns, marks, color — from typed YAML into Vega-Lite charts and HTML dashboards. Fields come from your semantic model, styling comes from your theme tokens, and the compile itself is plain deterministic code. Every chart, dashboard, and theme is a text file: diffed, reviewed, and reverted like the rest of your stack.

What dbt did for SQL transformations, Shelves does for charts and dashboards.

## Why

Analytics is stuck between two bad options.

**Traditional BI locks every chart inside a GUI.** Dashboards are opaque workbook state — unversionable, unreviewable, untestable. Theming is folklore. Every request goes through an analyst queue. The industry's answer was to bolt a chat box on top, but the chat's answers evaporate when the conversation ends. Nothing is left behind to review, reuse, or maintain.

**Pointing a coding agent at your warehouse is worse at scale.** It works — once. By the hundredth dashboard there are a hundred definitions of revenue, a hundred color palettes, and zero review trail.

Shelves puts a constrained intermediate representation between the prompt and the pixels:

```
prompt → YAML shelf grammar → (deterministic compiler) → chart
```

The grammar is small, typed, and validated, which makes it a far more reliable target for an LLM than raw Vega-Lite or React. Fields come only from the semantic layer's menu, so an agent can't hallucinate SQL or miscompute gross margin. Styling comes only from the theme layer, so it can't go off-brand.

## How it works

**1. Declare the model once.** Measures, dimensions, formats, and aggregations live in one place and get reused everywhere — so field logic is never copy-pasted between dashboards, and an agent has a closed menu of things it is allowed to reference.

```yaml
# models/orders.yaml
model: orders
label: Orders

source:
  type: file
  path: orders.csv

measures:
  revenue:
    column: Revenue
    aggregation: sum
    label: Revenue
    format: "$,.0f"

dimensions:
  region:
    column: Region
    label: Region
  order_date:
    column: Order Date
    type: temporal
    label: Order Date
    defaultGrain: month
```

**2. Write charts in shelves.** `cols` and `rows` are the x- and y-axis shelves; `marks` is how the data is drawn; `color`, `detail`, `size`, and `tooltip` are the remaining encoding channels. If you have used Tableau, you already know this grammar.

```yaml
# charts/revenue_by_region.yaml
sheet: "Revenue by Region"
data: orders

cols: region
rows: revenue
marks: bar
color: region
sort:
  field: revenue
  order: descending
```

**3. Compile.** `shelves-render` turns that into a standalone HTML file. The pipeline is deterministic — same spec, same pixels, every time — which is what makes snapshot testing your dashboards in CI possible.

## Install

```bash
pip install shelves-bi
```

For the flat-file path, install the optional DuckDB extra:

```bash
pip install 'shelves-bi[duckdb]'
```

Requires Python 3.11+.

## Quick start

Generate a model from a CSV — string columns become dimensions, numeric columns become measures, dates become temporal dimensions:

```bash
shelves-import sales.csv          # writes models/sales.yaml
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

## Two backends, one grammar

Shelves reads field types, formats, and sources from a semantic model that you can back two ways:

- **Start with a flat file.** Point a model at a local CSV, Parquet, or JSON file and Shelves queries it directly with [DuckDB](https://duckdb.org). Zero infrastructure — raw file to chart in seconds.
- **Grow into a semantic layer.** Point the same model at a [Cube.dev](https://cube.dev) instance when you want shared governed definitions across a team.

Only the model's `source` block changes:

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
  region:
    label: Region
  order_date:
    type: temporal
    label: Order Date
    defaultGrain: month
    format:
      month: "%b %Y"
```

Set `CUBE_API_URL` and `CUBE_API_TOKEN` in a `.env` file or as environment variables. Your existing charts keep working unchanged — a project can graduate from file to Cube without rewriting a single chart.

## The agent workflow

The reason the grammar is a file format and not a GUI:

1. An analyst assigns a ticket to a coding agent — *"add weekly revenue by region to the sales dashboard."*
2. The agent reads `models/orders.yaml`. It can only reference fields declared there.
3. It writes nine lines of YAML. Validation passes, with typed, correctable errors if it doesn't.
4. The preview renders on-brand, because theming is tokens rather than choices.
5. A reviewable PR lands:

```diff
+ # charts/weekly_revenue_by_region.yaml
+ sheet: "Weekly Revenue by Region"
+ data: orders
+
+ cols: order_date.week
+ rows: revenue
+ marks: line
+ color: region
+ tooltip: [order_date.week, region, revenue]
```

```diff
  # dashboards/sales.yaml
  root:
    orientation: vertical
    contains:
      - sheet: "revenue_by_region.yaml"
+     - sheet: "weekly_revenue_by_region.yaml"
```

Your teammates review the diff before they see the chart. That's the point.

Shelves is agent-agnostic — it is a target for whichever coding agent you already pay for, not a bundled chat.

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
          - sheet: "revenue_by_category.yaml"
            width: "60%"
          - sheet: "sales_over_time.yaml"
            width: "40%"
```

Sheet paths resolve relative to `--chart-dir` when it is given, and relative to the dashboard file otherwise.

```bash
# Dashboard (charts and models resolved from directories)
shelves-render dashboards/overview.yaml --chart-dir charts/ --models-dir models/

# Dev server with live reload
shelves-dev charts/revenue_by_category.yaml --models-dir models/

# Shelves Studio — local editor with live preview, file tree, and an
# integrated terminal for running your agent against the specs
shelves-studio
```

## Project structure

```
my-project/
  models/
    sales.yaml           # semantic model definitions (file or cube source)
    parameters.yaml      # named values referenced as $name in charts
  charts/
    revenue_by_category.yaml
    sales_over_time.yaml
  dashboards/
    overview.yaml
  themes/
    theme.yaml           # design tokens -> Vega-Lite config
  .env                   # CUBE_API_URL / CUBE_API_TOKEN (only for the Cube path)
```

## What works today

- **Charts** — bars, lines, areas, scatter, heatmaps, pies, KPIs; multi-measure stacked panels; dual-axis layers; faceting; filters; sort; data labels. All snapshot-tested.
- **Dashboards** — a nested-container layout DSL compiled to HTML through a constraint solver, with independent legends and interactive parameter controls.
- **Parameters** — declare named values once in `parameters.yaml`, reference them as `$name` across charts, filters, titles, and model calculations. Override from the CLI with `--param key=value`, or make them interactive with dashboard controls.
- **Semantic models** — flat files via DuckDB and Cube.dev, plus `shelves-import` to bootstrap a model from a CSV.
- **Theming** — design tokens compiled into Vega-Lite config; dark mode and multi-brand are token-set swaps.
- **Shelves Studio** — a local editor with Monaco, live preview, a file tree, and an integrated terminal. Dashboard controls recompile live.

## What doesn't, yet

Worth knowing before you adopt it:

- **Limited interactivity.** Parameter controls recompile in Studio, but cross-filtering and drill-down are not built. Exported dashboards are static — controls render read-only.
- **No tables or pivots.** The most-used visualization in real BI is missing.

Next up: an MCP server exposing the pipeline (list metrics, validate, compile, render) so any agent can drive it, and a public eval suite benchmarking prompt→DSL against prompt→raw-Vega-Lite across frontier models.

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
