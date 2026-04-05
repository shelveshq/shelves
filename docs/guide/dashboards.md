# Dashboards

Dashboards compose multiple charts, text blocks, navigation links, images, and spacers into a single HTML page. The Layout DSL arranges components in nested horizontal and vertical containers — the same model as Tableau's dashboard layout system.

The output is a static HTML page whose layout is computed by a solver into fixed pixel positions, rendered with standard block/inline-block CSS, and embedded Vega-Lite charts via vegaEmbed.

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

styles:
  card:
    background: "#FFFFFF"
    border_radius: 8
    shadow: "0 1px 3px rgba(0,0,0,0.1)"

root:
  orientation: vertical
  padding: 24
  gap: 20
  contains:
    - text: "Sales Overview"
      preset: title

    - horizontal:
        gap: 16
        contains:
          - sheet: charts/revenue_by_country.yaml
            width: "60%"
            style: card
            padding: 12
          - sheet: charts/weekly_trend.yaml
            style: card
            padding: 12
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
canvas:                                 # Optional (defaults: 1440×900)
  width: 1440
  height: 900

styles:                                 # Optional: reusable style presets
  card:
    background: "#FFFFFF"
    border_radius: 8

components:                             # Optional: predefined reusable components
  revenue_kpi:
    sheet: kpi_revenue.yaml
    style: card

root:                                   # Required: the layout tree
  orientation: vertical
  gap: 20
  contains:
    - ...
```

| Field | Required | Description |
|---|---|---|
| `dashboard` | Yes | Display name shown in the page title |
| `description` | No | Human-readable description |
| `canvas` | No | Fixed pixel dimensions (`width`, `height`). Defaults to 1440×900. |
| `styles` | No | Named style presets reusable across components |
| `components` | No | Predefined components that can be referenced by name in `contains` |
| `root` | Yes | The root container — the outermost layout element |

---

## Type-led syntax

Every element in a `contains` list starts with its **type as the YAML key**. You see *what* something is immediately — no hunting for a `type` field.

### Containers: `horizontal` and `vertical`

The type name *is* the orientation. No separate `orientation` field needed.

```yaml
- horizontal:
    gap: 16
    contains:
      - sheet: revenue.yaml
      - sheet: orders.yaml

- vertical:
    padding: 24
    gap: 12
    contains:
      - text: "Section Title"
        preset: heading
      - sheet: details.yaml
```

### Leaf types

The type key's value is always the component's **primary field**. Additional properties appear as sibling keys in the same YAML mapping:

```yaml
- sheet: revenue.yaml                    # just a chart
- sheet: revenue.yaml                    # chart with properties
  fit: width
  show_title: false
  style: card

- text: "Dashboard Title"               # just text
- text: "Dashboard Title"               # text with a preset
  preset: title

- image: logo.png                        # just an image
  alt: "Company Logo"
  height: 40

- button: "Export"                        # navigation button
  href: "/export"

- link: "Data Dictionary ↗"              # navigation link
  href: "/docs"
  target: _blank

- blank:                                 # empty spacer
- blank:                                 # spacer with explicit size
  height: 16
```

### Primary field reference

| Type | Primary field | Example |
|---|---|---|
| `sheet` | link (chart path) | `sheet: revenue.yaml` |
| `text` | content | `text: "Hello"` |
| `image` | src | `image: logo.png` |
| `button` | display text | `button: "Export"` |
| `link` | display text | `link: "Details"` |
| `blank` | *(none)* | `blank:` |

---

## Component types

### Containers — `horizontal`, `vertical`

Containers arrange their children along a main axis. The layout solver computes fixed pixel dimensions for each child.

```yaml
- horizontal:
    gap: 16
    padding: "12 24"
    style: header_bar
    contains:
      - image: logo.png
        height: 28
        width: 100
      - text: "Dashboard"
        preset: title
      - blank:                            # flex spacer — pushes nav right
      - button: "Details →"
        href: "/detail"
```

| Property | Required | Default | Description |
|---|---|---|---|
| `contains` | Yes | — | List of child components |
| `gap` | No | `0` | Pixels between children on the main axis |
| `width` | No | `auto` | Outer box width |
| `height` | No | `auto` | Outer box height |
| `padding` | No | `0` | Inner spacing (CSS shorthand) |
| `margin` | No | `0` | Outer spacing (CSS shorthand) |
| `style` | No | — | Reference to a shared style |
| `html` | No | — | Raw CSS escape hatch |

All children pack to the start (top-left origin). There are no `align` or `justify` keywords — the solver uses fixed-size inline blocks, not flexbox distribution.

### Sheet (chart embed)

Embeds a Chart DSL visualization.

```yaml
- sheet: revenue.yaml
  fit: width
  show_title: false
  style: card
  padding: 12
```

| Property | Required | Default | Description |
|---|---|---|---|
| *(value)* | Yes | — | Path to chart YAML file |
| `fit` | No | `fill` | Sizing mode: `fill`, `width`, or `height` |
| `show_title` | No | `true` | Whether to show the chart's Vega-Lite title |
| `name` | No | auto | Explicit HTML ID for the sheet |
| `width` | No | `auto` | Outer box width |
| `height` | No | `auto` | Outer box height |
| `padding` | No | `0` | Space between card edge and chart |
| `margin` | No | `0` | Outer spacing |
| `style` | No | — | Reference to a shared style |
| `html` | No | — | Raw CSS escape hatch |

**Sheet fit behavior:**

| Value | Behavior |
|---|---|
| `fill` (default) | Chart stretches to fill both dimensions. No scrolling. |
| `width` | Chart fills container width. Vertical scrolling if content overflows. |
| `height` | Chart fills container height. Horizontal scrolling if content overflows. |

**`show_title`:** When `false`, the chart's Vega-Lite title is suppressed. Useful when the dashboard provides its own section headings and the chart title would be redundant.

### Text

Static text blocks with optional presets for quick styling.

```yaml
- text: "Sales Performance Dashboard"
  preset: title

- text: "Updated daily · All figures in USD"
  preset: caption
  margin: "4 0 16 0"
```

| Property | Required | Default | Description |
|---|---|---|---|
| *(value)* | Yes | — | The text to display |
| `preset` | No | — | Built-in text preset (see table below) |
| `width` | No | `auto` | Outer box width |
| `height` | No | `auto` | Outer box height |
| `padding` | No | `0` | Inner spacing |
| `margin` | No | `0` | Outer spacing |
| `style` | No | — | Reference to a shared style |
| `html` | No | — | Raw CSS escape hatch |

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
- text: |
    Revenue metrics for Q4 2024.
    All figures in USD thousands.
  preset: caption
```

### Navigation — `button`, `link`

Buttons and links for dashboard-to-dashboard navigation. Rendered as `<a>` tags with different default styling.

```yaml
- button: "View Details →"
  href: "/dashboards/detail"

- link: "Data Dictionary ↗"
  href: "https://docs.example.com/data"
  target: _blank
```

| Property | Required | Default | Description |
|---|---|---|---|
| *(value)* | Yes | — | Button/link display text |
| `href` | Yes | — | Target URL or dashboard path |
| `target` | No | `_self` | `_self` or `_blank` |
| `width` | No | `auto` | Outer box width |
| `height` | No | `auto` | Outer box height |
| `padding` | No | `0` | Inner spacing |
| `margin` | No | `0` | Outer spacing |
| `style` | No | — | Reference to a shared style |
| `html` | No | — | Raw CSS escape hatch |

> **Note:** The URL property is `href` (not `link`) to avoid collision with the `link` type name.

**Default appearance:**

| Type | Background | Text style |
|---|---|---|
| `button` | Solid background, rounded corners, padding | White text |
| `link` | Transparent | Underlined, colored text |

### Image

Static images for logos or decorative graphics.

```yaml
- image: logo.svg
  alt: "Company Logo"
  height: 40
  width: 120
```

| Property | Required | Default | Description |
|---|---|---|---|
| *(value)* | Yes | — | Image file path or URL |
| `alt` | No | `""` | Alt text for accessibility (recommended) |
| `width` | No | `auto` | Outer box width |
| `height` | No | `auto` | Outer box height |
| `padding` | No | `0` | Inner spacing |
| `margin` | No | `0` | Outer spacing |
| `style` | No | — | Reference to a shared style |
| `html` | No | — | Raw CSS escape hatch |

### Blank (spacer)

Empty div for spacing or decorative dividers. Most spacing should use `gap` on containers — use `blank` for uneven spacing or visual dividers.

```yaml
# Fixed spacer
- blank:
  height: 16

# Flex spacer — pushes siblings apart
- blank:

# Horizontal divider line
- blank:
  width: "100%"
  height: 1
  background: "#E0E0E0"
```

---

## The root

The dashboard's outermost element. There is exactly one per dashboard. It behaves like a `vertical` or `horizontal` container but is constrained to the canvas dimensions.

```yaml
root:
  orientation: vertical          # Required: horizontal | vertical
  padding: 24
  gap: 20
  contains:
    - ...
```

The root does **not** use type-led syntax — it is always `root:` with an explicit `orientation` field. This is the one exception to the type-led pattern, because the root is a fixed structural element, not a child in a `contains` list.

---

## Predefined components

Components are a **separation of concerns** mechanism. The `components` block is where you define *what things look like* — styling, content, and structure. The `root` tree is where you define *how things are arranged* — position, order, and spatial relationships. Even elements used only once benefit from this pattern when it improves clarity.

### Defining components

Each entry uses the same type-led syntax as the tree. Components are complete as defined:

```yaml
components:
  revenue_kpi:
    sheet: kpi_revenue.yaml
    style: card

  orders_kpi:
    sheet: kpi_orders.yaml
    style: card

  company_logo:
    image: logo.svg
    alt: "Company Logo"
    height: 28
    width: 100
```

Components can also be containers:

```yaml
components:
  kpi_row:
    horizontal:
      gap: 16
      height: 120
      contains:
        - sheet: kpi_revenue.yaml
          style: card
        - sheet: kpi_orders.yaml
          style: card
        - sheet: kpi_growth.yaml
          style: card
```

### Using components

Reference a component by name in `contains` as a bare string. It is inserted as-is — no overrides, no merging:

```yaml
root:
  orientation: vertical
  gap: 20
  contains:
    - company_logo
    - kpi_row
    - horizontal:
        gap: 16
        contains:
          - sheet: revenue.yaml
          - sheet: orders.yaml
```

### Rules

1. **No overrides at usage.** Components are used as-is. If you need a variation, define a separate component or use inline types directly.
2. **Components cannot reference other components.** A component's definition may only use known types, never other component names.
3. **Component names must not shadow type names.** A component named `horizontal`, `sheet`, etc. is rejected at parse time.

### When to use components vs inline

Use components to separate **what things look like** from **where they go**. This keeps the `root` tree scannable:

```yaml
# Define appearance
components:
  revenue_chart:
    sheet: revenue.yaml
    style: card
    padding: 12
  header:
    text: "Sales Dashboard"
    preset: title

# Arrange layout
root:
  orientation: vertical
  gap: 20
  contains:
    - header
    - revenue_chart
```

Use inline types when the element is simple enough that the tree stays readable:

```yaml
root:
  orientation: vertical
  gap: 20
  contains:
    - text: "Sales Dashboard"
      preset: title
    - sheet: revenue.yaml
      style: card
      padding: 12
```

Both are equivalent — it's a readability judgment call.

---

## Sizing

All components accept `width` and `height` in these formats:

| Format | Example | Behavior |
|---|---|---|
| Integer | `300` | Fixed 300px |
| Pixel string | `"300px"` | Fixed 300px (equivalent to integer) |
| Percentage | `"50%"` | 50% of the parent's content box on that axis |
| `"auto"` or omitted | — | Fill remaining space (shared equally with other `auto` children) |

### Main axis vs cross axis

- In a **horizontal** container: `width` is the main axis, `height` is the cross axis
- In a **vertical** container: `height` is the main axis, `width` is the cross axis

Along the **main axis**, the solver resolves sizes in priority order:
1. **Percentages** — computed as a fraction of the parent's content box
2. **Fixed pixels** — reserved at their exact value
3. **Auto** — remaining space divided equally among auto children

Along the **cross axis**, components default to 100% of the parent (minus their own margins) unless an explicit size is set.

### Gap

Containers support a `gap` property — uniform spacing between children on the main axis. Gap is subtracted from the distributable space before child sizes are resolved.

```yaml
- horizontal:
    gap: 16                    # 16px between each child
    contains:
      - sheet: a.yaml
      - sheet: b.yaml
      - sheet: c.yaml          # total gap: 16 × 2 = 32px
```

Use `gap` instead of per-child margins for uniform spacing. It's cleaner and handles any number of children.

### Margin and padding

Both use CSS-style shorthand:

```yaml
padding: 16              # 16px all sides
padding: "8 16"          # 8px vertical, 16px horizontal
padding: "8 16 12 16"    # top right bottom left
```

**Border-box model:** An element's specified size is its outer box. Padding shrinks the content area inward. Margins are additional spacing between elements.

---

## Shared styles

Define reusable visual presets in the `styles` block, then reference them by name with `style:`:

```yaml
styles:
  card:
    background: "#FFFFFF"
    border: "1px solid #E5E7EB"
    border_radius: 8
    shadow: "0 1px 3px rgba(0,0,0,0.08)"

  header_bar:
    background: "#F8F9FA"
    border_bottom: "1px solid #DEE2E6"
```

Apply a style and optionally override individual properties inline:

```yaml
- sheet: revenue.yaml
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
- text: "QUARTERLY REVIEW"
  preset: heading
  html: "text-transform: uppercase; letter-spacing: 2px;"
```

### Style resolution order

When multiple style sources apply, later sources override earlier ones:

```
theme defaults → text preset → shared style → inline properties → html (wins all)
```

---

## Complete examples

### KPI dashboard with header

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
    shadow: "0 1px 3px rgba(0,0,0,0.08)"

components:
  kpi_revenue:
    sheet: charts/kpi_revenue.yaml
    style: card
  kpi_orders:
    sheet: charts/kpi_orders.yaml
    style: card
  kpi_arpu:
    sheet: charts/kpi_arpu.yaml
    style: card
  kpi_customers:
    sheet: charts/kpi_customers.yaml
    style: card

root:
  orientation: vertical
  padding: 24
  gap: 20
  contains:

    # ── Header ──
    - horizontal:
        height: 56
        gap: 12
        background: "#F8F9FA"
        border_bottom: "1px solid #DEE2E6"
        padding: "0 16"
        contains:
          - image: assets/logo.svg
            alt: "Acme Corp"
            height: 28
            width: 100
          - text: "Sales Overview"
            preset: title
            font_size: 20
          - blank:                        # pushes nav to the right
          - button: "Detailed Report →"
            href: "/dashboards/sales_detail"

    # ── KPI Row ──
    - horizontal:
        height: 120
        gap: 16
        contains:
          - kpi_revenue
          - kpi_orders
          - kpi_arpu
          - kpi_customers

    # ── Charts Row ──
    - horizontal:
        gap: 16
        contains:
          - sheet: charts/revenue_by_country.yaml
            width: "60%"
            style: card
            padding: 12
          - sheet: charts/orders_trend.yaml
            style: card
            padding: 12
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
    shadow: "0 1px 3px rgba(0,0,0,0.08)"

root:
  orientation: horizontal
  contains:

    # ── Sidebar ──
    - vertical:
        width: 220
        background: "#1E293B"
        padding: "24 16"
        gap: 8
        contains:
          - image: assets/logo_white.svg
            height: 24
            width: 100
          - blank:
            height: 16
          - button: "Overview"
            href: "/dashboards/overview"
            color: "#FFFFFF"
            html: "font-weight: bold;"
          - button: "Sales"
            href: "/dashboards/sales"
            color: "#94A3B8"
          - button: "Customers"
            href: "/dashboards/customers"
            color: "#94A3B8"

    # ── Main content ──
    - vertical:
        padding: 24
        gap: 16
        contains:
          - text: "Executive Summary"
            preset: title
          - text: "Updated daily · All figures in USD"
            preset: caption

          - horizontal:
              gap: 16
              contains:
                - sheet: charts/revenue_trend.yaml
                  width: "65%"
                  style: card
                  padding: 12
                - sheet: charts/revenue_by_region.yaml
                  style: card
                  padding: 12

          - sheet: charts/order_details.yaml
            style: card
            padding: 12
```

### Separation of concerns with components

Define appearance in `components`, arrange layout in `root`:

```yaml
dashboard: "Multi-Page Overview"
canvas: { width: 1440, height: 900 }

styles:
  card:
    background: "#FFFFFF"
    border_radius: 8
    shadow: "0 1px 3px rgba(0,0,0,0.08)"

components:
  page_title:
    text: "Overview"
    preset: title

  kpi_revenue:
    sheet: charts/kpi_revenue.yaml
    style: card

  kpi_orders:
    sheet: charts/kpi_orders.yaml
    style: card

  kpi_row:
    horizontal:
      height: 140
      gap: 16
      contains:
        - sheet: charts/kpi_revenue.yaml
          style: card
        - sheet: charts/kpi_orders.yaml
          style: card

root:
  orientation: vertical
  padding: 24
  gap: 20
  contains:
    - page_title
    - kpi_row
    - horizontal:
        gap: 16
        contains:
          - sheet: charts/revenue.yaml
            width: "60%"
            style: card
            padding: 12
          - sheet: charts/orders.yaml
            style: card
            padding: 12
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
