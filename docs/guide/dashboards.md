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
          - sheet: revenue_by_country.yaml
            width: "60%"
            style: card
            padding: 12
          - sheet: weekly_trend.yaml
            style: card
            padding: 12
```

### 3. Render the dashboard

```bash
# Render to HTML
shelves-render dashboards/sales_overview.yaml --chart-dir charts/

# With a custom theme
shelves-render dashboards/sales_overview.yaml --chart-dir charts/ --theme my_theme.yaml
```

The output is a self-contained HTML file with all charts embedded.

### Chart paths

A `sheet:` value is resolved against a **base directory**:

- `--chart-dir` when you pass it, or
- **the directory containing the dashboard file** when you don't.

The path is then joined onto that base, with no implicit `charts/` prefix ever
added. So with charts in `charts/` and the dashboard in `dashboards/`, as above,
you pass `--chart-dir charts/` and write the bare filename:

```yaml
- sheet: revenue_by_country.yaml     # ✅ resolves to charts/revenue_by_country.yaml
- sheet: charts/revenue_by_country.yaml   # ❌ resolves to charts/charts/revenue_by_country.yaml
```

Without `--chart-dir`, the same bare filename resolves to
`dashboards/revenue_by_country.yaml` — which is correct only if the chart sits
next to the dashboard file. The examples throughout this guide use bare
filenames and assume `--chart-dir` is set.

The same rule applies to a `legend:` link, which takes the same path as the
`sheet:` it matches.

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

- parameter: metric                      # parameter widget
- parameter: status                      # parameter with label override
  label: "Order Status"

- filter: region                         # interactive filter
  model: orders

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
| `legend` | source (chart path) | `legend: revenue.yaml` |
| `parameter` | parameter name | `parameter: metric` |
| `filter` | field name | `filter: region` |
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

**Cross-axis sizing follows the Tableau model: children always fill the container on the cross axis.** Only the *main axis* (the container's flow direction) is sized per child:

- In a **horizontal** container, `width` sizes a child along the row; its `height` is ignored — the child fills the row's height.
- In a **vertical** container, `height` sizes a child down the column; its `width` is ignored — the child fills the column's width.

Setting a cross-axis size emits a warning and has no effect. To center or inset a child, use `padding` on the container or a `blank` spacer object — there is no cross-axis alignment keyword.

```yaml
root:
  orientation: vertical
  contains:
    - sheet: kpi.yaml
      height: 120        # main-axis size — a 120px-tall band
      # `width` here would be ignored; the card fills the column width
    - horizontal:
        height: 300      # main-axis size of this row within the column
        contains:
          - sheet: a.yaml
            width: 400   # main-axis size — 400px wide within the row
            # `height` here would be ignored; the chart fills the row height
```

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

Padding is always preserved: clipping and scrolling apply to the chart content
only, never to the sheet's padding. A chart that overflows is clipped (or
scrolled) at the inner content edge, so the configured padding stays visible on
all sides regardless of chart size.

**Stacked multi-measure charts:** a sheet whose chart stacks several measures
(`rows`/`cols` authored as a list) renders as multiple panels — stacked vertically
when the measures are on `rows`, horizontally when they're on `cols`. Each panel is
given the **same** plot size (even rectangles), and the whole stack is sized to fit
the sheet exactly: the panels fill the sheet, the shared axis, the per-panel value
axes, and the chart title all get the room they actually need, and nothing is
clipped. The gap between panels shrinks proportionally as the panels are compressed,
so a tightly-fit stack keeps its spacing in proportion to the panel size rather than
leaving an oversized gap (the chart's natural spacing is the upper bound — the gap
only shrinks, never grows past it). Suppressing the chart title with
`show_title: false` returns that space to the panels.

This sizing is measured in the browser at render time — the actual rendered size of
the axes and title is read back and the panels are sized to match — so it stays
correct regardless of orientation, font sizes, or how long the axis labels are.

**Faceted charts:** a sheet whose chart facets a measure across a dimension
(`facet.field` + `columns`, or `facet.row` / `facet.column`) renders as a grid of
small multiples. Like stacked panels, the grid is sized in the browser to fill the
sheet in **both** directions: the number of rows and columns is determined from the
chart's data, the real size of the facet headers, axes, and title is measured, and
every cell is given the same size so the grid fills the sheet without overflowing
its height. Inter-cell spacing shrinks proportionally when the grid is compressed,
exactly as it does for stacked panels.

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

**Parameter interpolation:** text values support `${name}` references to
project-level parameters. For example, `text: "Showing ${metric}"` resolves
the parameter before rendering. This works at any nesting depth inside
`root.contains` and in `components` text.

**Overflow:** text is clipped to its box and rendered on a single line; text that
is too long for the box is truncated with an ellipsis (`…`). Size the box (via
`width`/`height` on the component or its container) to fit the content, or shorten
the text. Multi-line wrapping inside a fixed-size text box is not supported — each
text component renders on one line.

**Text presets** (values come from your theme):

| Preset | Default size | Weight | Color |
|---|---|---|---|
| `title` | 24px | bold | primary |
| `subtitle` | 18px | 600 | secondary |
| `heading` | 16px | 600 | primary |
| `body` | 14px | normal | primary |
| `caption` | 12px | normal | tertiary |
| `label` | 11px | 500 | secondary |

A text component renders on a single line (see **Overflow** above). YAML block
scalars and other newlines are collapsed to spaces — they do not produce visible
line breaks. To stack multiple lines, use a separate `text` component for each
line inside a vertical container:

```yaml
- vertical:
    contains:
      - text: "Revenue metrics for Q4 2024."
        preset: caption
      - text: "All figures in USD thousands."
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
- image: png/logo.png    # path relative to your assets directory
  alt: "Company Logo"
  height: 40
  width: 120
  fit: true       # scale to fit the box (preserve aspect); false = natural size + scroll
  center: false   # top-left within the box; true = centered (only applies when fit: true)
```

| Property | Required | Default | Description |
|---|---|---|---|
| *(value)* | Yes | — | Image source: an assets-relative path, external URL, or data URI (see **Image paths** below) |
| `alt` | No | `""` | Alt text for accessibility (recommended) |
| `fit` | No | `true` | `true`: scale the image to fit its box, preserving aspect ratio. `false`: render at natural size; the box scrolls if the image overflows. |
| `center` | No | `false` | `true`: center the image in its box. `false`: anchor to the top-left. Only applies when `fit: true`. |
| `width` | No | `auto` | Outer box width |
| `height` | No | `auto` | Outer box height |
| `padding` | No | `0` | Inner spacing |
| `margin` | No | `0` | Outer spacing |
| `style` | No | — | Reference to a shared style |
| `html` | No | — | Raw CSS escape hatch (applied last, overrides `fit`/`center`) |

> **Box vs. content.** In a horizontal/vertical container the image's *box* always
> stretches to fill the cross axis (the Tableau layout model). `fit` and `center`
> control how the image *content* sits inside that box — they do not resize the box.
> This mirrors Tableau's image options: fit-to-box on/off, centered on/off.

#### Image paths

An image `src` (the value after `image:`) can be one of three things:

**1. A path relative to the assets directory.** Put image files anywhere under
your assets directory — **including subfolders** — and reference them by the path
*inside* that directory. Don't include the `assets/` folder name itself; just
like a `sheet:` is named relative to its base directory (see
[Chart paths](#chart-paths)), an `image:` is named relative to the assets
directory:

| File on disk (under the assets dir) | `src` to write |
|---|---|
| `logo.png` | `logo.png` |
| `png/logo.png` | `png/logo.png` |
| `brand/icons/star.svg` | `brand/icons/star.svg` |

The assets directory defaults to `<project>/assets` and is configurable on every
CLI:

```bash
shelves-studio --assets-dir ./assets
shelves-dev dashboard.yaml --assets-dir ./assets
shelves-render dashboard.yaml --assets-dir ./assets --out out/dash.html
```

`shelves-studio` and `shelves-dev` serve the assets directory and resolve these
paths automatically in the live preview. `shelves-render` writes a standalone
HTML file and emits a path relative to that file's location (e.g.
`../assets/png/logo.png` when rendering into an `output/` subfolder), so the
image resolves when the HTML is opened from disk.

**2. An external URL** — e.g. `https://example.com/logo.png` (and
protocol-relative `//example.com/logo.png`). Passed through unchanged.

**3. An inline data URI** — e.g. `data:image/png;base64,iVBORw0KGgo…`. Useful
for embedding a small image directly in the dashboard with no external file.

### Legend

An independent legend for a chart, placed as its own box in the layout instead of
inside the chart. A legend links to exactly one sheet by its **chart path** (the
same path you would give a `sheet:`) and names the **field** whose scale it shows.

```yaml
- legend: sales_by_category.yaml   # same path as the chart's `sheet:` link
  field: Category                   # which encoded field's scale to show
  title: "Product Category"         # optional; defaults to the field's label
  orientation: vertical             # vertical (default) or horizontal
  width: 180
  style: card
```

The `legend:` value is the **same path you give the matching `sheet:`** — resolved
against the same base directory, with no implicit `charts/` prefix. See
[Chart paths](#chart-paths).

| Property | Required | Default | Description |
|---|---|---|---|
| *(value)* | Yes | — | `source`: the chart YAML path this legend describes (must match the sheet's path) |
| `field` | Yes | — | Name of the encoded field whose scale the legend renders |
| `title` | No | field label | Legend heading; defaults to the field's model label |
| `orientation` | No | `vertical` | `vertical` (stacked list) or `horizontal` (wrapping row) |
| `width` | No | `auto` | Outer box width |
| `height` | No | `auto` | Outer box height |
| `padding` | No | `0` | Inner spacing |
| `margin` | No | `0` | Outer spacing |
| `style` | No | — | Reference to a shared style |
| `html` | No | — | Raw CSS escape hatch |

The in-sheet legend on the linked chart is hidden automatically so the legend is
not drawn twice — and **every** in-sheet legend on a dashboard chart is suppressed,
whether or not you place a matching `legend:` element. If a chart has a colour or
size legend and no `legend:` element points at it, the dashboard build emits a
warning so the legend doesn't silently disappear. Sizing and styling follow the
same rules as every other layout element (see [Sizing](#sizing) and
[Shared styles](#shared-styles)).

> Legends link to a **single-view** chart's `color` or `size` field. A
> **categorical** colour legend (ordinal/nominal scale) renders a swatch + label
> list; a **gradient** colour legend (quantitative scale) renders a sampled
> colour bar with min/mid/max ticks; and a **size** legend (quantitative scale)
> renders graduated circle glyphs at increasing radius with value labels. Tick
> and glyph labels use the field's model format. All render either vertical
> (default) or horizontal per `orientation`, headed by `title` (defaulting to the
> field's model label), with the in-sheet legend suppressed. Legends pointing at
> layered or dual-axis charts (multiple scales per channel) are not supported yet
> and raise a build error.

### Parameter widget

An interactive widget for a declared parameter. The widget type is inferred from the parameter's `type` and `values` shape — no author-chosen widget override.

```yaml
- parameter: metric                  # dropdown (type: field)
- parameter: status                  # dropdown (literal values)
  label: "Order Status"              # overrides the parameter label
- parameter: top_n                   # stepper (type: number + range)
```

| Property | Required | Default | Description |
|---|---|---|---|
| *(value)* | Yes | — | `param`: the declared parameter name |
| `label` | No | parameter label or name | Display title for the widget |
| `width` | No | `auto` | Outer box width |
| `height` | No | `auto` | Outer box height |
| `padding` | No | `0` | Inner spacing |
| `margin` | No | `0` | Outer spacing |
| `style` | No | — | Reference to a shared style |
| `html` | No | — | Raw CSS escape hatch |

**Widget inference:**

| Parameter shape | Widget | HTML element |
|---|---|---|
| `type: field` with `values:` | Dropdown | `<select>` of field names |
| Literal `values:` list | Dropdown | `<select>` of literal values |
| Field-reference domain | Dropdown | `<select>` of resolved domain values |
| `type: number` with `min`/`max` range | Stepper | `<input type="number">` |
| `type: date` with `min`/`max` range | Date picker | `<input type="date">` |
| `type: string` with no `values:` | Text input | `<input type="text">` |

**Label precedence:** inline `label:` on the `parameter:` component > `label:` on the parameter declaration > parameter name.

**Studio interactivity:** In Shelves Studio, changing a parameter widget recompiles the dashboard with the new value. In exported HTML (`shelves-render`), parameter widgets render as disabled read-only controls — parameters are compile-time and there is no server to recompile against.

**Theming:** the rendered widgets are styled via the `layout.control` theme block. This theming is shared with the upcoming `filter:` leaf type — both parameter and filter widgets use the same control styling tokens.

The `parameter:` component must reference a declared parameter (from `parameters.yaml`). An unknown parameter name produces a build error, identical to an unresolved legend source.

### Filter (interactive filter)

A dashboard-level filter bound to a semantic model field. Filters target sheets that use the same model and will (in a future release) inject Vega-Lite transforms to filter the data at render time. Currently, filters are schema-validated and compose-time validated but not yet compiled or rendered.

```yaml
- filter: region                     # field name from the model
  model: orders                      # required: which semantic model
  mode: multi                        # optional: filter interaction mode
  targets: all                       # optional: which sheets to filter (default: all)
  default: "EMEA"                    # optional: default filter value
  label: "Region Filter"             # optional: display label
```

| Property | Required | Default | Description |
|---|---|---|---|
| *(value)* | Yes | — | `field`: the model field this filter controls |
| `model` | Yes | — | Semantic model name (must match a model in the models directory) |
| `targets` | No | `"all"` | `"all"` (every sheet using this model) or a list of sheet names |
| `mode` | No | inferred | Filter interaction mode (see table below) |
| `default` | No | `null` (unfiltered) | Default filter value |
| `label` | No | field label | Display label for the filter widget |
| `width` | No | `auto` | Outer box width |
| `height` | No | `auto` | Outer box height |
| `padding` | No | `0` | Inner spacing |
| `margin` | No | `0` | Outer spacing |
| `style` | No | — | Reference to a shared style |
| `html` | No | — | Raw CSS escape hatch |

**Filter modes by field type:**

| Field type | Valid modes | Description |
|---|---|---|
| Dimension (nominal/ordinal) | `multi`, `single`, `wildcard` | Select one or more categorical values |
| Quantitative (measure) | `range`, `at_least`, `at_most` | Numeric range or threshold |
| Temporal | `range`, `after`, `before` | Date range or boundary |

When `mode` is omitted, it will be inferred from the field type at compile time (not yet implemented).

**Compose-time validation:** the dashboard build validates that the filter's model and field exist, that the mode is compatible with the field type, that target sheets exist, and that target sheets use the same model as the filter. Validation errors are reported at build time.

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

The root container follows the same cross-axis rule as any container: its direct children always fill the cross axis, and only their main-axis size is honored.

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

Along the **cross axis**, components always fill 100% of the parent (minus their own margins). A cross-axis size is ignored (and warns) — only main-axis sizing is a per-child concept. See [Containers](#containers) for the Tableau-model rationale.

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
| `padding` | int or string | Inner spacing (CSS shorthand) |
| `margin` | int or string | Outer spacing (CSS shorthand) |

Example — a card style with padding:

```yaml
styles:
  card:
    background: "#FFFFFF"
    border_radius: 8
    padding: 12
```

If a component also sets `padding` inline, the inline value wins and a warning is emitted.

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
    sheet: kpi_revenue.yaml
    style: card
  kpi_orders:
    sheet: kpi_orders.yaml
    style: card
  kpi_arpu:
    sheet: kpi_arpu.yaml
    style: card
  kpi_customers:
    sheet: kpi_customers.yaml
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
          - image: logo.svg
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
          - sheet: revenue_by_country.yaml
            width: "60%"
            style: card
            padding: 12
          - sheet: orders_trend.yaml
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
          - image: logo_white.svg
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
                - sheet: revenue_trend.yaml
                  width: "65%"
                  style: card
                  padding: 12
                - sheet: revenue_by_region.yaml
                  style: card
                  padding: 12

          - sheet: order_details.yaml
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
    sheet: kpi_revenue.yaml
    style: card

  kpi_orders:
    sheet: kpi_orders.yaml
    style: card

  kpi_row:
    horizontal:
      height: 140
      gap: 16
      contains:
        - sheet: kpi_revenue.yaml
          style: card
        - sheet: kpi_orders.yaml
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
          - sheet: revenue.yaml
            width: "60%"
            style: card
            padding: 12
          - sheet: orders.yaml
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
| `layout.control.surface` | Background color for parameter and filter widgets |
| `layout.control.border` | Border color for parameter and filter widgets |
| `layout.control.radius` | Border radius (px) for parameter and filter widgets |
| `layout.control.font_size` | Font size (px) for parameter and filter widgets |
| `layout.control.height` | Widget height (px) for parameter and filter widgets |

All preset values come from the theme — they are never hardcoded. This means your charts and dashboard chrome share a coherent visual identity from a single theme file.

The `layout.control` block styles interactive widgets rendered by both `parameter:` and the upcoming `filter:` leaf types. Customize these tokens in your `theme.yaml` to match your brand:
