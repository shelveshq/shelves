# Dashboards

Dashboards compose multiple charts, text blocks, navigation links, images, and spacers into a single HTML page. The Layout DSL arranges components in nested horizontal and vertical containers — the same model as Tableau's dashboard layout system.

The output is a static HTML page with CSS flexbox layout and embedded Vega-Lite charts via vegaEmbed.

---

## Quick start

### 1. Create your charts

First, create individual chart YAML files as described in the [DSL Reference](./dsl-reference.md):

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

```yaml
# charts/weekly_trend.yaml
sheet: "Weekly Revenue Trend"
data: orders
cols: week
rows: revenue
marks: line
```

### 2. Create a dashboard YAML file

A dashboard file has four top-level keys: `dashboard`, `canvas`, `root`, and optionally `styles` and `components`.

```yaml
# dashboards/sales_overview.yaml

dashboard: "Sales Overview"
canvas:
  width: 1440
  height: 900

root:
  type: root
  orientation: vertical
  contains:
    - type: text
      content: "Sales Overview"
      preset: title
      padding: "16 24"

    - charts_row:
        type: container
        orientation: horizontal
        padding: "0 24"
        contains:
          - revenue_chart:
              type: sheet
              link: "charts/revenue_by_country.yaml"
              width: "60%"
          - trend_chart:
              type: sheet
              link: "charts/weekly_trend.yaml"
              width: "40%"
```

### 3. Render the dashboard

```bash
# Render to HTML
python -m src.cli.render dashboards/sales_overview.yaml

# With a custom theme
python -m src.cli.render dashboards/sales_overview.yaml --theme my_theme.yaml
```

The output is a self-contained HTML file with all charts embedded.

---

## Document structure

Every dashboard YAML file has this shape:

```yaml
dashboard: "Display Name"              # Required: dashboard title
description: "Optional description"    # Optional
canvas:                                 # Required: fixed canvas size
  width: 1440
  height: 900

styles:                                 # Optional: reusable style presets
  card:
    background: "#FFFFFF"
    border_radius: 8
    padding: 16

components:                             # Optional: pre-defined components
  kpi_revenue:
    type: sheet
    link: "charts/kpi_revenue.yaml"

root:                                   # Required: the layout tree
  type: root
  orientation: vertical
  contains:
    - ...
```

| Field | Required | Description |
|---|---|---|
| `dashboard` | Yes | Display name shown in the page title |
| `description` | No | Human-readable description |
| `canvas` | Yes | Fixed pixel dimensions (`width`, `height`) |
| `styles` | No | Named style presets reusable across components |
| `components` | No | Named components that can be referenced by string in `contains` |
| `root` | Yes | The root container — the outermost layout element |

---

## Component types

### Container (`root` / `container`)

Containers arrange their children horizontally or vertically using CSS flexbox. The `root` is a special container that receives the canvas dimensions — there's exactly one per dashboard.

```yaml
root:
  type: root
  orientation: vertical
  padding: 16
  contains:
    - header:
        type: container
        orientation: horizontal
        height: 56
        contains:
          - ...
    - body:
        type: container
        orientation: horizontal
        contains:
          - ...
```

| Property | Required | Description |
|---|---|---|
| `orientation` | Yes | `horizontal` or `vertical` |
| `contains` | Yes | List of child components |
| `align` | No | Cross-axis alignment: `start`, `center`, `end`, `stretch` (default) |
| `justify` | No | Main-axis alignment: `start` (default), `center`, `end`, `between`, `around`, `evenly` |

### Sheet (chart embed)

References a Chart DSL YAML file. Named sheets get stable HTML IDs for vegaEmbed.

```yaml
revenue_chart:
  type: sheet
  link: "charts/revenue_by_country.yaml"
  width: "60%"
  style: card
```

| Property | Required | Description |
|---|---|---|
| `link` | Yes | Path to a chart YAML file |

### Text

Static text blocks with optional presets for quick styling.

```yaml
- type: text
  content: "Sales Performance Dashboard"
  preset: title

- type: text
  content: "Updated daily · All figures in USD"
  preset: caption
  margin: "4 0 16 0"
```

| Property | Required | Description |
|---|---|---|
| `content` | Yes | The text string to display |
| `preset` | No | Built-in text style: `title`, `subtitle`, `heading`, `body`, `caption`, `label` |

**Text presets** (values come from your theme):

| Preset | Default size | Weight | Color |
|---|---|---|---|
| `title` | 24px | bold | primary |
| `subtitle` | 18px | 600 | secondary |
| `heading` | 16px | 600 | primary |
| `body` | 14px | normal | primary |
| `caption` | 12px | normal | tertiary |
| `label` | 11px | 500 | secondary |

Multi-line text uses YAML block scalars:

```yaml
- type: text
  content: |
    Revenue metrics for Q4 2024.
    All figures in USD thousands.
  preset: caption
```

### Navigation

Buttons or links for dashboard-to-dashboard navigation. Three type aliases with different default styling:

```yaml
# Button style (default)
- type: navigation
  text: "View Details →"
  link: "/dashboards/detail"
  background: "#4A90D9"
  color: "#FFFFFF"

# Explicit button type — identical to above
- type: navigation_button
  text: "View Details →"
  link: "/dashboards/detail"

# Link style — underlined text, no background
- type: navigation_link
  text: "Data Dictionary ↗"
  link: "https://docs.example.com/data"
  target: _blank
```

| Property | Required | Description |
|---|---|---|
| `text` | Yes | Button/link label |
| `link` | Yes | Target URL or dashboard path |
| `target` | No | `_self` (default) or `_blank` |

### Image

Static images for logos or decorative graphics.

```yaml
- type: image
  src: "assets/logo.svg"
  alt: "Company Logo"
  height: 28
  width: auto
```

| Property | Required | Description |
|---|---|---|
| `src` | Yes | Image file path or URL |
| `alt` | No | Alt text for accessibility (recommended) |

### Blank (spacer)

Empty div for spacing, dividers, or pushing siblings apart.

```yaml
# Fixed spacer
- type: blank
  width: 16
  height: 16

# Flex spacer — pushes siblings apart
- type: blank
  width: auto

# Horizontal divider line
- type: blank
  width: "100%"
  height: 1
  background: "#E0E0E0"
```

---

## The `contains` list

Containers accept three shapes of children in their `contains` list. Mix freely.

### String reference

References a named component from the `components` block:

```yaml
components:
  kpi_revenue:
    type: sheet
    link: "charts/kpi_revenue.yaml"

root:
  type: root
  orientation: vertical
  contains:
    - kpi_revenue              # string reference
```

### Inline anonymous

Define a component directly — no name, used once:

```yaml
contains:
  - type: text
    content: "Updated daily"
    preset: caption
  - type: blank
    width: 10
```

### Inline named

Define a named component inline. The name becomes an HTML ID for sheets:

```yaml
contains:
  - revenue_chart:
      type: sheet
      link: "charts/revenue.yaml"
      width: "60%"
```

### Mixing all three

```yaml
contains:
  - logo                            # string reference
  - type: text                      # inline anonymous
    content: "Sales Overview"
    preset: title
  - type: blank                     # flex spacer
    width: auto
  - detail_nav:                     # inline named
      type: navigation
      text: "Details →"
      link: "/dashboards/detail"
```

---

## Sizing

All components accept `width` and `height` in these formats:

| Format | Example | Behavior |
|---|---|---|
| Integer | `300` | Fixed 300px |
| Percentage | `"50%"` | 50% of parent |
| `auto` | `"auto"` | Fill remaining space equally |
| Omitted | — | Same as `auto` — fill remaining space |

**Main-axis vs cross-axis:**

- In a **horizontal** container: `width` is the main axis, `height` is cross axis
- In a **vertical** container: `height` is the main axis, `width` is cross axis
- Main-axis sizing controls flex behavior (`flex: 0 0 300px` for fixed, `flex: 1` for auto)
- Cross-axis defaults to `100%` (fill parent)

**Margin and padding** use CSS shorthand:

```yaml
padding: 16              # 16px all sides
padding: "8 16"          # 8px vertical, 16px horizontal
padding: "8 16 12 16"    # top right bottom left
```

---

## Shared styles

Define reusable style presets in the `styles` block, then reference them by name:

```yaml
styles:
  card:
    background: "#FFFFFF"
    border: "1px solid #E5E7EB"
    border_radius: 8
    padding: 16
    shadow: "0 1px 3px rgba(0,0,0,0.08)"

  header_bar:
    background: "#F8F9FA"
    border_bottom: "1px solid #DEE2E6"
    padding: "12 24"

root:
  type: root
  orientation: vertical
  contains:
    - revenue_chart:
        type: sheet
        link: "charts/revenue.yaml"
        style: card                        # apply shared style
        background: "#F0F8FF"              # override one property
```

**Available style properties:**

| Property | Type | Description |
|---|---|---|
| `background` | string | Background color or value |
| `border` | string | CSS border shorthand |
| `border_top/bottom/left/right` | string | Individual border sides |
| `border_radius` | int or string | Corner radius (int = px) |
| `shadow` | string | CSS box-shadow |
| `opacity` | float (0-1) | Opacity |
| `font_size` | int | Font size (px) |
| `font_weight` | string or int | Font weight |
| `font_family` | string | Font family override |
| `color` | string | Text color |
| `text_align` | string | `left`, `center`, or `right` |

### The `html` escape hatch

Every component accepts an `html` property — a raw CSS string for niche properties not covered by dedicated keywords:

```yaml
- type: text
  content: "QUARTERLY REVIEW"
  preset: heading
  html: "text-transform: uppercase; letter-spacing: 2px;"

- type: sheet
  link: "charts/big_scatter.yaml"
  width: "100%"
  html: "overflow: auto; min-height: 400px;"
```

### Style resolution order

When multiple style sources apply, later sources override earlier ones:

```
theme defaults → text preset → shared style → inline properties → html (wins all)
```

---

## Complete examples

### KPI dashboard with header and navigation

```yaml
dashboard: "Sales Overview"
description: "Weekly sales KPIs and revenue trends"
canvas:
  width: 1440
  height: 900

styles:
  card:
    background: "#FFFFFF"
    border: "1px solid #E5E7EB"
    border_radius: 8
    padding: 16
    shadow: "0 1px 3px rgba(0,0,0,0.08)"

root:
  type: root
  orientation: vertical
  contains:

    # ── Header ──
    - header:
        type: container
        orientation: horizontal
        height: 56
        padding: "0 24"
        background: "#F8F9FA"
        border_bottom: "1px solid #DEE2E6"
        html: "align-items: center;"
        contains:
          - logo:
              type: image
              src: "assets/logo.svg"
              alt: "Acme Corp"
              height: 28
              width: auto
          - type: text
            content: "Sales Overview"
            preset: title
            font_size: 20
            margin: "0 0 0 12"
          - type: blank
            width: auto
          - type: navigation
            text: "Detailed Report →"
            link: "/dashboards/sales_detail"
            background: "#4A90D9"
            color: "#FFFFFF"
            border_radius: 6
            padding: "6 16"

    # ── KPI Row ──
    - kpi_row:
        type: container
        orientation: horizontal
        height: 140
        padding: "16 24"
        contains:
          - kpi_revenue:
              type: sheet
              link: "charts/kpi_revenue.yaml"
              style: card
              margin: "0 8 0 0"
          - kpi_orders:
              type: sheet
              link: "charts/kpi_orders.yaml"
              style: card
              margin: "0 8 0 0"
          - kpi_arpu:
              type: sheet
              link: "charts/kpi_arpu.yaml"
              style: card
              margin: "0 8 0 0"
          - kpi_customers:
              type: sheet
              link: "charts/kpi_customers.yaml"
              style: card

    # ── Charts Row ──
    - chart_row:
        type: container
        orientation: horizontal
        padding: "0 24"
        contains:
          - revenue_chart:
              type: sheet
              link: "charts/revenue_by_country.yaml"
              width: "60%"
              style: card
              margin: "0 8 0 0"
          - orders_chart:
              type: sheet
              link: "charts/orders_trend.yaml"
              width: "40%"
              style: card
```

### Sidebar navigation dashboard

```yaml
dashboard: "Executive Summary"
canvas:
  width: 1440
  height: 900

styles:
  card:
    background: "#FFFFFF"
    border: "1px solid #E5E7EB"
    border_radius: 8
    padding: 16

  nav_link:
    color: "#94A3B8"
    font_size: 14

root:
  type: root
  orientation: horizontal
  contains:

    # ── Sidebar ──
    - sidebar:
        type: container
        orientation: vertical
        width: 220
        background: "#1E293B"
        padding: "24 16"
        contains:
          - type: image
            src: "assets/logo_white.svg"
            height: 24
            width: auto
          - type: blank
            height: 24
          - type: navigation_link
            text: "Overview"
            link: "/dashboards/overview"
            style: nav_link
            color: "#FFFFFF"
            html: "font-weight: bold;"
          - type: navigation_link
            text: "Sales"
            link: "/dashboards/sales"
            style: nav_link
            margin: "8 0 0 0"
          - type: navigation_link
            text: "Customers"
            link: "/dashboards/customers"
            style: nav_link
            margin: "8 0 0 0"

    # ── Main content ──
    - main:
        type: container
        orientation: vertical
        padding: 24
        contains:
          - type: text
            content: "Executive Summary"
            preset: title
          - type: text
            content: "Updated daily · All figures in USD"
            preset: caption
            margin: "4 0 16 0"

          - chart_row:
              type: container
              orientation: horizontal
              contains:
                - revenue_trend:
                    type: sheet
                    link: "charts/revenue_trend.yaml"
                    width: "65%"
                    style: card
                    margin: "0 8 0 0"
                - revenue_by_region:
                    type: sheet
                    link: "charts/revenue_by_region.yaml"
                    width: "35%"
                    style: card
```

### Pre-defined components (DRY)

Use the `components` block to define reusable elements, then reference them by name:

```yaml
dashboard: "Multi-Page Overview"
canvas: { width: 1440, height: 900 }

styles:
  card: { background: "#FFF", border_radius: 8, padding: 16 }

components:
  kpi_revenue: { type: sheet, link: "charts/kpi_revenue.yaml", style: card, margin: "0 8 0 0" }
  kpi_orders: { type: sheet, link: "charts/kpi_orders.yaml", style: card }

  kpi_row:
    type: container
    orientation: horizontal
    height: 140
    contains: [kpi_revenue, kpi_orders]

root:
  type: root
  orientation: vertical
  contains:
    - type: text
      content: "Overview"
      preset: title
      padding: "16 24"
    - kpi_row                        # string reference to pre-defined container
    - chart_area:
        type: container
        orientation: horizontal
        padding: "16 24"
        contains:
          - revenue: { type: sheet, link: "charts/revenue.yaml", width: "60%", style: card, margin: "0 8 0 0" }
          - orders: { type: sheet, link: "charts/orders.yaml", width: "40%", style: card }
```

---

## Theme integration

Dashboards use the `layout` section of your `theme.yaml` for default typography, colors, and text presets. See [Theme](dsl-reference.md#theme) for the full theme file format.

Key theme tokens used by dashboards:

| Token | What it controls |
|---|---|
| `layout.font.family.body` | Default font for all dashboard text |
| `layout.text.primary` | Primary text color (used by title, heading, body presets) |
| `layout.text.secondary` | Secondary text color (used by subtitle, label presets) |
| `layout.text.tertiary` | Tertiary text color (used by caption preset) |
| `layout.surface` | Default surface/card background |
| `layout.background` | Dashboard canvas background |
| `layout.border` | Default border color |
| `layout.presets.*` | Text preset definitions (font_size, font_weight, color) |

All preset values come from the theme — they are never hardcoded. This means your charts and dashboard chrome share a coherent visual identity from a single theme file.
