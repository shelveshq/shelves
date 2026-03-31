# Layout DSL Specification: Dashboard Composition Grammar

This document defines the Layout DSL — a YAML grammar for composing dashboards as nested containers of static and embedded components. It translates deterministically to fixed-size HTML divs via a layout solver.

Scope: **static layout and navigation only**. Interactive features (filters, parameters, cross-chart actions) are deferred to a future revision.

---

## 1. Design Philosophy

### 1.1 Principles

- **Tableau's dashboard model.** Horizontal and vertical containers nest arbitrarily deep. Anyone who has built a Tableau dashboard recognizes this structure.
- **The tree IS the layout.** Containers define their children inline via `contains`. You read the YAML top-to-bottom and see the dashboard structure directly — containers near their children, no separate arrangement step.
- **Three ways to place a child.** A `contains` list accepts string references (to pre-defined components), inline anonymous definitions (quick spacers, labels), and inline named definitions (sheets, sub-containers). Mix freely.
- **Fixed canvas.** Dashboards are authored at a fixed pixel size (e.g., 1440×900). No responsive breakpoints in v1.
- **Solver-based sizing.** Users specify sizes in `%`, `px`, or `auto`. A deterministic layout solver resolves every element to concrete pixel dimensions before rendering. The user never thinks about CSS flex algorithms — percentages mean what they intuitively mean.
- **Start-aligned packing.** All children pack to the start of their container (top-left origin). Remaining space stays empty. There is no justify or distribution keyword. This matches Tableau's behavior.
- **Border-box model.** An element's specified size is its outer box. Padding shrinks the content area inward. Margins are additional spacing between elements, subtracted from the container's available space before size distribution.
- **Shared styles with inline overrides.** A `styles` dictionary defines reusable presets. Components reference by name and override inline. `html` property provides a raw CSS escape hatch that supersedes everything.
- **No interactivity (v1).** Output is static HTML/CSS with Vega-Lite embeds. Navigation between dashboards is the only "interactive" element — it's just an `<a>` tag.
- **Minimal keywords.** The core vocabulary is ~48 keywords. Niche CSS properties are handled by the `html` escape hatch rather than dedicated DSL keywords.

### 1.2 Relationship to Other Layers

```
Layout DSL (this spec)          Chart DSL              Theme
─────────────────────          ─────────              ─────
Defines WHERE things go         Defines WHAT charts    Defines HOW everything
on the dashboard canvas.        look like.             is styled by default.

Translates to:                  Translates to:         Merges into:
Fixed-size HTML divs            Vega-Lite JSON         Both chart specs and
(via layout solver)                                    layout HTML
```

---

## 2. Document Structure

```yaml
# dashboard_name.yaml

dashboard: "Sales Overview"              # Required: display name
description: "Weekly sales KPIs..."      # Optional
canvas:                                   # Required
  width: 1440
  height: 900

styles:                                   # Optional: reusable style presets
  card:
    background: "#FFFFFF"
    border_radius: 8

components:                               # Optional: pre-defined components
  kpi_revenue:
    type: sheet
    link: "charts/kpi_revenue.yaml"

root:                                     # Required: the dashboard layout
  type: root
  orientation: vertical
  contains:
    - ...
```

---

## 3. Keyword Reference

### 3.1 Core Keywords (every user needs these)

| Keyword | Used On | Description |
|---|---|---|
| `type` | all components | Component type: `root`, `container`, `sheet`, `text`, `navigation`, `navigation_button`, `navigation_link`, `image`, `blank` |
| `width` | all components | Sizing: integer (px), `"50%"`, `"auto"`, or omitted |
| `height` | all components | Sizing: integer (px), `"50%"`, `"auto"`, or omitted |
| `margin` | all components | Outer spacing (CSS shorthand: `16`, `"8 16"`, `"8 16 8 16"`) |
| `padding` | all components | Inner spacing (CSS shorthand: same format as margin) |
| `style` | all components | Reference to a shared style name from `styles` block |
| `html` | all components | Raw CSS string — escape hatch, supersedes all other styling |
| `orientation` | root, container | `horizontal` \| `vertical` |
| `contains` | root, container | List of children (three shapes: ref, anonymous, named) |
| `link` | sheet, navigation | Sheet: path to chart YAML. Navigation: target URL or dashboard path. |
| `content` | text | The text string to display |
| `preset` | text | Built-in text preset: `title`, `subtitle`, `heading`, `body`, `caption`, `label` |
| `text` | navigation | Button/link label |
| `src` | image | Image file path or URL |
| `alt` | image | Alt text for accessibility |
| `fit` | sheet | Chart fitting mode: `fill` (default), `width`, `height` |
| `background` | style / inline | Background color or value |
| `border` | style / inline | CSS border shorthand |
| `border_radius` | style / inline | Corner radius (int → px) |
| `opacity` | style / inline | 0–1 float |
| `font_size` | style / inline | Font size (int → px) |
| `color` | style / inline | Text/font color |
| `text_align` | style / inline | `left` \| `center` \| `right` |

### 3.2 Advanced Keywords (power users, hidden from basic examples)

| Keyword | Used On | Description | Default |
|---|---|---|---|
| `target` | navigation | `_self` \| `_blank` | `_self` |
| `font_weight` | style / inline | Font weight (`"bold"`, `600`, etc.) | From preset/theme |
| `font_family` | style / inline | Font family override | From theme |
| `border_top` | style / inline | Top border only | — |
| `border_bottom` | style / inline | Bottom border only | — |
| `border_left` | style / inline | Left border only | — |
| `border_right` | style / inline | Right border only | — |
| `shadow` | style / inline | CSS box-shadow | — |

### 3.3 The `html` Escape Hatch

Every component accepts an `html` property — a raw CSS string injected as inline style. It supersedes all other styling (theme, preset, shared style, inline overrides).

Use for niche CSS that doesn't warrant a dedicated keyword: `text-shadow`, `letter-spacing`, `text-transform`, `object-fit`, `min-width`, `line-height`, `cursor`, gradients, transforms, etc.

```yaml
- type: text
  content: "QUARTERLY REVIEW"
  preset: heading
  html: "text-transform: uppercase; letter-spacing: 2px; text-shadow: 1px 1px 2px rgba(0,0,0,0.1);"
```

**Resolution order:**

```
theme defaults → text preset → shared style → inline properties → html (wins all)
```

---

## 4. The `contains` List — Three Child Shapes

### 4.1 String Reference

```yaml
contains:
  - kpi_revenue              # looks up from components block
```

### 4.2 Inline Anonymous

```yaml
contains:
  - type: blank              # no name, used once
    width: 10
  - type: text
    content: "Updated daily"
    preset: caption
```

### 4.3 Inline Named

```yaml
contains:
  - revenue_chart:
      type: sheet
      link: "charts/revenue.yaml"
      width: 60%
```

### 4.4 Mixing All Three

```yaml
contains:
  - logo                            # string reference
  - type: text                      # inline anonymous
    content: "Sales Overview"
    preset: title
  - type: blank                     # inline anonymous spacer
    width: auto
  - detail_nav:                     # inline named
      type: navigation
      text: "Details →"
      link: "/dashboards/detail"
```

### 4.5 Containers as Children

Containers can be children in all three forms. A pre-defined container brings its `contains` list along:

```yaml
components:
  kpi_row:
    type: container
    orientation: horizontal
    contains:
      - kpi_1: { type: sheet, link: "charts/kpi_1.yaml" }
      - kpi_2: { type: sheet, link: "charts/kpi_2.yaml" }

root:
  type: root
  orientation: vertical
  contains:
    - kpi_row                        # pre-defined container, children included
    - chart_row:                     # inline named container
        type: container
        orientation: horizontal
        contains:
          - revenue: { type: sheet, link: "charts/revenue.yaml", width: "60%" }
          - orders: { type: sheet, link: "charts/orders.yaml", width: "40%" }
```

---

## 5. Component Types

### 5.1 Root Container

The dashboard's outermost element. Behaves like `container` but is constrained to the canvas dimensions. There is exactly one per dashboard.

**Critical rule:** The root element never exceeds the canvas size. If the root has margin, the margin is subtracted from the canvas dimensions inward — the root's outer box shrinks to fit within the canvas, and its content area shrinks further by padding. The canvas is an absolute boundary.

```yaml
root:
  type: root
  orientation: vertical
  padding: 0
  background: "#F5F5F5"
  contains:
    - ...
```

**Root sizing example:**

```
Canvas: 1440 × 900
Root margin: 16 (all sides)
Root padding: 24 (all sides)

Root outer box:  1440 - 32 = 1408 × 900 - 32 = 868  (margin shrinks the box)
Root content box: 1408 - 48 = 1360 × 868 - 48 = 820  (padding shrinks content)

Children are laid out within the 1360 × 820 content box.
```

### 5.2 Container

Arranges children horizontally or vertically.

```yaml
header:
  type: container
  orientation: horizontal        # Required: horizontal | vertical
  width: 100%                    # Optional
  height: 56                     # Optional
  margin: 0                      # Optional
  padding: "0 24"                # Optional
  style: header_bar              # Optional
  background: "#F8F9FA"          # Optional: any inline style
  html: ""                       # Optional: raw CSS override
  contains:                      # Required
    - ...
```

### 5.3 Sheet (Chart Embed)

Placeholder referencing a Chart DSL YAML file. Named sheets get stable HTML IDs for vegaEmbed.

```yaml
revenue_chart:
  type: sheet
  link: "charts/revenue_by_country.yaml"   # Required: path to chart YAML
  width: 50%                               # Optional
  height: 100%                             # Optional
  fit: fill                                # Optional: fill (default), width, height
  margin: 0                                # Optional
  padding: 16                              # Optional
  style: card                              # Optional
  html: ""                                 # Optional
```

**The `fit` property** controls how the Vega-Lite chart relates to the sheet's solved pixel rect. This mirrors Tableau's fit options:

| `fit` value | Behavior | Vega-Lite sizing | CSS overflow |
|---|---|---|---|
| `fill` (default) | Chart fills the entire content area. No scrolling. | `width` and `height` from solved rect | `overflow: hidden` |
| `width` | Chart scales to content area width. Scrolls vertically if chart is taller. | `width` from solved rect; `height` is chart's natural height | `overflow-x: hidden; overflow-y: auto` |
| `height` | Chart scales to content area height. Scrolls horizontally if chart is wider. | `height` from solved rect; `width` is chart's natural width | `overflow-y: hidden; overflow-x: auto` |

### 5.4 Text

Static text blocks. Use `preset` for quick styling, override with inline properties or `html`.

```yaml
type: text
content: "Sales Performance Dashboard"    # Required
preset: title                             # Optional
width: auto                               # Optional
height: 40                                # Optional
color: "#4A90D9"                          # Optional: text color
font_size: 20                             # Optional: override preset
html: ""                                  # Optional
```

**Text overflow:** Text elements render with `overflow: hidden`. If the content exceeds the solved dimensions, it is clipped. The user adjusts the element's height as needed. No scrolling, no auto-expansion — the solver's output is deterministic.

**Text presets:**

| Preset | font_size | font_weight | color | text_align |
|---|---|---|---|---|
| `title` | 24 | bold | theme.text.primary | left |
| `subtitle` | 18 | 600 | theme.text.secondary | left |
| `heading` | 16 | 600 | theme.text.primary | left |
| `body` | 14 | normal | theme.text.primary | left |
| `caption` | 12 | normal | theme.text.tertiary | left |
| `label` | 11 | 500 | theme.text.secondary | left |

**Multi-line text:**

```yaml
- type: text
  content: |
    Revenue metrics for Q4 2024.
    All figures in USD thousands.
  preset: caption
```

### 5.5 Navigation

Buttons or links for dashboard navigation. The only "interactive" element — rendered as `<a>`. Three type aliases control the default styling:

| Type | Alias for | Default appearance |
|---|---|---|
| `navigation` | `navigation_button` | Button with background, padding, rounded corners |
| `navigation_button` | — | Same as above |
| `navigation_link` | — | Text link with underline, no background |

All three accept the same properties and are styled with the same standard keywords (`background`, `color`, `border_radius`, `padding`, etc.). The type just sets different defaults.

```yaml
# Button (type: navigation is shorthand for navigation_button)
detail_btn:
  type: navigation
  text: "View Detailed Report →"       # Required: label
  link: "/dashboards/detail_report"     # Required: URL or dashboard path
  background: "#4A90D9"               # Optional
  color: "#FFFFFF"                     # Optional
  border_radius: 6                     # Optional
  padding: "8 20"                     # Optional

# Link type — underlined text, no background
docs_link:
  type: navigation_link
  text: "Data Dictionary ↗"
  link: "https://docs.example.com/data"
  target: _blank                        # advanced: open in new tab
  color: "#4A90D9"
```

### 5.6 Image

Static images for logos, decorative graphics, or inline visuals.

```yaml
logo:
  type: image
  src: "assets/logo.svg"            # Required: path or URL
  alt: "Company Logo"               # Optional (recommended)
  width: 120                        # Optional
  height: auto                      # Optional
  style: null                       # Optional
  html: ""                          # Optional: e.g. "object-fit: cover;"
```

Default `object-fit` is `contain`. Override via `html: "object-fit: cover;"` if needed.

**Image sizing in the solver:** If both dimensions are specified, use them. If one dimension is specified and the other is `auto` or omitted, the solver treats the unspecified dimension as `auto` (equal share of remaining space on that axis). Aspect-ratio-aware sizing from the actual image file is deferred to a future version — in v1, images with one unspecified dimension fill available space and rely on `object-fit: contain` in the browser to preserve aspect ratio visually.

### 5.7 Blank (Spacer)

Empty div for spacing or decorative dividers.

```yaml
# Simple spacer
- type: blank
  width: 16
  height: 16

# Flex spacer — pushes siblings apart
- type: blank
  width: auto

# Horizontal divider
- type: blank
  width: 100%
  height: 1
  background: "#E0E0E0"
```

---

## 6. Styles System

### 6.1 Defining Shared Styles

```yaml
styles:
  card:
    background: "#FFFFFF"
    border: "1px solid #E0E0E0"
    border_radius: 8
    padding: 16
    shadow: "0 1px 3px rgba(0,0,0,0.1)"

  dark_card:
    background: "#1A1A2E"
    border: "none"
    border_radius: 12
    padding: 20

  header_bar:
    background: "#F8F9FA"
    border_bottom: "1px solid #DEE2E6"
    padding: "12 24"
```

### 6.2 Available Style Properties

**Box model** (all components):

| Property | Type | CSS Output |
|---|---|---|
| `background` | string | `background` |
| `border` | string | `border` |
| `border_radius` | int or string | `border-radius` (int → px) |
| `opacity` | float (0–1) | `opacity` |

**Text** (text and navigation components):

| Property | Type | CSS Output |
|---|---|---|
| `font_size` | int | `font-size` (→ px) |
| `color` | string | `color` |
| `text_align` | `left` \| `center` \| `right` | `text-align` |

**Advanced** (available but not featured in basic examples):

`border_top`, `border_bottom`, `border_left`, `border_right`, `shadow`, `font_weight`, `font_family`

**Anything else:** Use `html` escape hatch.

### 6.3 Applying Styles

```yaml
- revenue_chart:
    type: sheet
    link: "charts/revenue.yaml"
    style: card                        # shared style
    background: "#F0F8FF"              # inline override
    html: "transition: all 0.2s;"      # raw CSS, wins everything
```

### 6.4 Resolution Order

```
theme defaults → text preset → shared style → inline properties → html (wins all)
```

---

## 7. Sizing Model

### 7.1 Overview

Shelves uses a **layout solver** that resolves every element to concrete pixel dimensions before rendering. The user writes sizes in `%`, `px`, or `auto`; the solver computes exact pixel rects for the entire dashboard tree. The output HTML contains only fixed-size divs — no CSS flex algorithms run in the browser.

```
YAML DSL → Pydantic parse → Layout Solver → Resolved pixel tree → HTML (fixed divs)
```

### 7.2 Box Model

Shelves uses **border-box** semantics throughout:

- An element's specified **size** is its **outer box** (the space it occupies in the parent).
- **Padding** shrinks the **content area** inward without changing the outer box size.
- **Margin** is additional spacing between elements. Margins are not part of the element's box — they reduce the parent container's available space for size distribution.

```
┌─── container content box ────────────────────────────────────┐
│                                                              │
│  ┌─ margin ─┐                        ┌─ margin ─┐           │
│  │          │                        │          │           │
│  │  ┌──── element outer box ────┐    │  ┌──── element ──┐   │
│  │  │                           │    │  │               │   │
│  │  │  ┌── padding ──────────┐  │    │  │  ┌─────────┐  │   │
│  │  │  │                     │  │    │  │  │         │  │   │
│  │  │  │   content area      │  │    │  │  │ content │  │   │
│  │  │  │   (chart / text)    │  │    │  │  │         │  │   │
│  │  │  │                     │  │    │  │  │         │  │   │
│  │  │  └─────────────────────┘  │    │  │  └─────────┘  │   │
│  │  │                           │    │  │               │   │
│  │  └───────────────────────────┘    │  └───────────────┘   │
│  │          │                        │          │           │
│  └──────────┘                        └──────────┘           │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 7.3 Value Formats

| Format | Example | Meaning |
|---|---|---|
| Integer | `300` | 300 pixels |
| Pixel string | `"300px"` | 300 pixels (equivalent to integer) |
| Percentage | `"50%"` | 50% of the container's content box on this axis |
| `"auto"` | `"auto"` | Fill remaining space (shared equally with other `auto` children) |
| Omitted | — | Same as `auto` |

### 7.4 Margin & Padding Shorthand

Both use CSS shorthand notation:

| DSL Value | Meaning |
|---|---|
| `16` | 16px all sides |
| `"8 16"` | 8px top/bottom, 16px left/right |
| `"8 16 12 16"` | 8px top, 16px right, 12px bottom, 16px left |

---

## 8. Layout Solver Algorithm

The solver walks the dashboard tree top-down, starting from the root. At each node it computes concrete pixel dimensions for all children based on the container's available space.

### 8.1 Root Resolution

The root is special: it is always constrained to the canvas.

```
root_outer_width  = canvas.width  - root.margin_left - root.margin_right
root_outer_height = canvas.height - root.margin_top  - root.margin_bottom
root_content_width  = root_outer_width  - root.padding_left - root.padding_right
root_content_height = root_outer_height - root.padding_top  - root.padding_bottom
```

The canvas is an absolute boundary. Root margin shrinks the root inward; it never expands the canvas outward.

### 8.2 Container Resolution

Given a container with solved dimensions (`container_content_W` × `container_content_H`) and `N` children, the solver distributes space on the **main axis** (width for `horizontal`, height for `vertical`):

**Step 1 — Compute the content box.**

Already known from the parent's resolution: `container_content_W` × `container_content_H`.

**Step 2 — Subtract all child margins.**

Sum every child's margin on the main-axis sides. For a horizontal container:

```
total_margin = Σ (child.margin_left + child.margin_right)  for all children
```

This gives the **distributable space**:

```
distributable = container_content_W - total_margin     (horizontal)
distributable = container_content_H - total_margin     (vertical)
```

**Step 3 — Classify children into three buckets.**

| Bucket | Condition | Example |
|---|---|---|
| A: Percentage | Main-axis size is a `%` value | `width: "60%"` |
| B: Fixed px | Main-axis size is an integer or `"Npx"` | `width: 300` |
| C: Auto | Main-axis size is `"auto"` or omitted | `width: auto` |

**Step 4 — Resolve sizes in priority order.**

Percentages resolve against the **content box** (pre-margin), not the distributable space. This means `width: "50%"` always means "half the container" regardless of sibling margins:

```
resolved_A = Σ (percentage × container_content_main_axis)  for Bucket A
resolved_B = Σ (fixed_px_value)                            for Bucket B
total_claimed = resolved_A + resolved_B
```

**Case 1: Everything fits** (`total_claimed ≤ distributable`):

- Bucket A and B children get their resolved sizes.
- Remaining space (`distributable - total_claimed`) is divided equally among Bucket C children.
- If there are no Bucket C children, the remaining space is empty (packed to start).

**Case 2: Overconstrained** (`total_claimed > distributable`):

Priority cascade — honor percentages first, then shrink fixed sizes:

1. If `resolved_A ≤ distributable`: Bucket A sizes are honored. Bucket B children share the remaining space (`distributable - resolved_A`) proportionally to their original px values. Bucket C children get 0px.
2. If `resolved_A > distributable`: Even percentages exceed available space. **All children** (A, B, and C) are shrunk proportionally from their resolved values to fit within `distributable`. The solver emits a warning.

**Step 5 — Cross-axis resolution.**

Every child gets 100% of the container's content box on the cross axis, unless the child specifies an explicit cross-axis value. For a horizontal container:

```
child_height = container_content_H                          (default)
child_height = explicit_value                               (if specified)
child_height = percentage × container_content_H             (if % specified)
```

**Step 6 — Compute child content areas.**

Each child's content area is its outer box minus its own padding:

```
child_content_W = child_outer_W - child.padding_left - child.padding_right
child_content_H = child_outer_H - child.padding_top  - child.padding_bottom
```

**Step 7 — Recurse.**

For any child that is a container, recurse with its content area as the new available space.

### 8.3 Worked Example

```yaml
canvas: { width: 1440, height: 900 }

root:
  type: root
  orientation: vertical
  padding: 24
  contains:
    - header:
        type: container
        orientation: horizontal
        height: 56
        padding: "0 16"
        contains:
          - logo: { type: image, width: 120, height: 28 }
          - type: text
            content: "Dashboard"
            preset: title
            margin: "0 0 0 12"
          - type: blank
            width: auto
          - type: navigation
            text: "Details →"
            width: 140
            padding: "6 16"
    - chart_row:
        type: container
        orientation: horizontal
        padding: 16
        margin: "16 0 0 0"
        contains:
          - main_chart:
              type: sheet
              link: "charts/revenue.yaml"
              width: "60%"
              padding: 16
              margin: "0 8 0 0"
          - side_chart:
              type: sheet
              link: "charts/orders.yaml"
              padding: 16
```

**Solver trace:**

```
ROOT
  canvas:          1440 × 900
  root margin:     0 (all sides)
  root outer:      1440 × 900
  root padding:    24 (all sides)
  root content:    1392 × 852

HEADER (vertical child of root, height: 56)
  main-axis (vertical): explicit 56px → outer_H = 56
  cross-axis: default 100% → outer_W = 1392
  padding: 0 16 → content: 1360 × 56

  HEADER CHILDREN (horizontal, distributable after margins):
    Margins: logo=0, text=12 left, blank=0, nav=0 → total = 12
    Distributable: 1360 - 12 = 1348

    Bucket B (fixed): logo=120, nav=140 → 260
    Bucket C (auto): text, blank
    Remaining: 1348 - 260 = 1088 → 544 each for text, blank

    logo:       120 × 56 (cross-axis default, minus padding → content: 120 × 56)
    text:       544 × 56  content: 544 × 56
    blank:      544 × 56  content: 544 × 56
    nav:        140 × 56  content: 108 × 44 (padding 6 16 → minus 32 W, 12 H)

CHART_ROW (vertical child of root, auto height)
  main-axis (vertical): auto → only child remaining after header
    header claimed 56px. Margin on chart_row: 16 top.
    Distributable for vertical: 852 - 56 - 16 = 780
    chart_row outer_H = 780
  cross-axis: 1392
  padding: 16 → content: 1360 × 748

  CHART_ROW CHILDREN (horizontal):
    Margins: main_chart = 8 right, side_chart = 0 → total = 8
    Distributable: 1360 - 8 = 1352

    Bucket A (%): main_chart = 60% of 1360 (content box) = 816
    Bucket C (auto): side_chart
    Remaining: 1352 - 816 = 536

    main_chart: 816 × 748  content: 784 × 716 (padding 16)
    side_chart: 536 × 748  content: 504 × 716 (padding 16)

Vega-Lite specs receive:
  revenue.yaml → width: 784, height: 716
  orders.yaml  → width: 504, height: 716
```

### 8.4 Solver Warnings

The solver emits warnings (never errors) for constraint violations. The dashboard still renders — the solver makes its best effort.

| Condition | Warning message | Solver behavior |
|---|---|---|
| Children's fixed + % sizes exceed distributable space | "Children in `{container}` exceed available space by {N}px; fixed sizes reduced proportionally" | Shrink Bucket B proportionally after honoring Bucket A |
| Even percentages exceed distributable space | "Percentage allocations in `{container}` total {N}% and exceed available space; all sizes reduced proportionally" | Shrink all children proportionally |
| Auto child receives 0px | "Auto-sized child `{name}` in `{container}` received 0px on main axis; container is fully claimed by explicit sizes" | Child renders at 0px (invisible) |
| Child content area is negative (padding > outer box) | "Padding on `{name}` ({P}px) exceeds its solved size ({S}px); content area clamped to 0" | Content area = 0, element renders as padding-only box |

---

## 9. Complete Examples

### 9.1 KPI Dashboard with Navigation

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
        contains:
          - logo:
              type: image
              src: "assets/logo.svg"
              alt: "Acme Corp"
              height: 28
              width: 100
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
            width: 180

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
              width: 60%
              fit: fill
              style: card
              margin: "0 8 0 0"
          - orders_chart:
              type: sheet
              link: "charts/orders_trend.yaml"
              fit: width
              style: card
```

### 9.2 Sidebar Navigation Dashboard

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
            width: 100
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
          - type: navigation_link
            text: "Products"
            link: "/dashboards/products"
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

          - kpi_row:
              type: container
              orientation: horizontal
              height: 120
              margin: "0 0 16 0"
              contains:
                - kpi_revenue: { type: sheet, link: "charts/kpi_revenue.yaml", style: card, margin: "0 8 0 0" }
                - kpi_orders: { type: sheet, link: "charts/kpi_orders.yaml", style: card, margin: "0 8 0 0" }
                - kpi_margin: { type: sheet, link: "charts/kpi_margin.yaml", style: card }

          - chart_row:
              type: container
              orientation: horizontal
              contains:
                - revenue_trend:
                    type: sheet
                    link: "charts/revenue_trend.yaml"
                    width: 65%
                    style: card
                    margin: "0 8 0 0"
                - revenue_by_region:
                    type: sheet
                    link: "charts/revenue_by_region.yaml"
                    width: 35%
                    style: card
```

### 9.3 Pre-defined Components

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
    - kpi_row
    - chart_area:
        type: container
        orientation: horizontal
        padding: "16 24"
        contains:
          - revenue: { type: sheet, link: "charts/revenue.yaml", width: "60%", style: card, margin: "0 8 0 0" }
          - orders: { type: sheet, link: "charts/orders.yaml", style: card }
```

---

## 10. Translation Rules

### 10.1 Pipeline

```
YAML DSL
  → Pydantic parse (DashboardSpec)
  → Layout Solver (produces ResolvedTree with pixel rects)
  → HTML Renderer (fixed-size divs + vegaEmbed)
```

### 10.2 Component → HTML

Every component is rendered as a fixed-size HTML element. Sizes come from the solver, not from CSS layout algorithms.

| Type | HTML | Key styles |
|---|---|---|
| `root` | `<div>` | `width: {solved}px; height: {solved}px; position: relative; overflow: hidden;` |
| `container` | `<div>` | `width: {solved}px; height: {solved}px; box-sizing: border-box;` |
| `sheet` | `<div>` | `width: {solved}px; height: {solved}px; box-sizing: border-box;` + overflow from `fit` |
| `text` | `<div>` | `width: {solved}px; height: {solved}px; overflow: hidden;` |
| `navigation` / `navigation_button` | `<a>` | Button styles; `link` → `href`, optional `target` |
| `navigation_link` | `<a>` | Link styles; `link` → `href`, optional `target` |
| `image` | `<img>` | `width: {solved}px; height: {solved}px; object-fit: contain;` |
| `blank` | `<div>` | `width: {solved}px; height: {solved}px;` |

### 10.3 Sheet `fit` → CSS

| `fit` | CSS on the sheet div |
|---|---|
| `fill` | `overflow: hidden;` |
| `width` | `overflow-x: hidden; overflow-y: auto;` |
| `height` | `overflow-y: hidden; overflow-x: auto;` |

### 10.4 Style Resolution

```
theme defaults → text preset → shared style → inline properties → html (wins all)
```

### 10.5 Tree Walker

```python
@dataclass
class ResolvedNode:
    """Output of the layout solver for a single element."""
    name: str | None
    component: Component
    outer_width: int          # solved outer box width in px
    outer_height: int         # solved outer box height in px
    content_width: int        # outer minus padding
    content_height: int       # outer minus padding
    children: list[ResolvedNode]  # empty for leaf types

def render_node(node: ResolvedNode, styles: dict, theme: Theme) -> str:
    css = resolve_styles(node.component, styles, theme)
    css += f"width: {node.outer_width}px; height: {node.outer_height}px; box-sizing: border-box;"

    margin = resolve_margin(node.component)
    if margin:
        css += f" margin: {margin};"

    padding = resolve_padding(node.component)
    if padding:
        css += f" padding: {padding};"

    if node.component.type in ("root", "container"):
        css += " overflow: hidden;"
        inner = "".join(render_node(c, styles, theme) for c in node.children)
        return f'<div style="{css}">{inner}</div>'

    elif node.component.type == "sheet":
        fit = getattr(node.component, "fit", "fill")
        if fit == "fill":
            css += " overflow: hidden;"
        elif fit == "width":
            css += " overflow-x: hidden; overflow-y: auto;"
        elif fit == "height":
            css += " overflow-y: hidden; overflow-x: auto;"
        sheet_id = f"sheet-{node.name}" if node.name else f"sheet-{id(node)}"
        return f'<div id="{sheet_id}" style="{css}"></div>'

    elif node.component.type == "text":
        css += " overflow: hidden;"
        return f'<div style="{css}">{node.component.content}</div>'

    elif node.component.type in ("navigation", "navigation_button", "navigation_link"):
        t = f' target="{node.component.target}"' if node.component.target != "_self" else ""
        return f'<a href="{node.component.link}"{t} style="{css}">{node.component.text}</a>'

    elif node.component.type == "image":
        css += " object-fit: contain;"
        return f'<img src="{node.component.src}" alt="{node.component.alt}" style="{css}">'

    elif node.component.type == "blank":
        return f'<div style="{css}"></div>'
```

### 10.6 Vega-Lite Embedding

Because the solver resolves sheet dimensions before rendering, Vega-Lite specs receive explicit pixel sizes. No `container` sizing mode, no ResizeObserver.

```python
def embed_spec(sheet: ResolvedNode, chart_spec: dict) -> dict:
    """Inject solved dimensions into the Vega-Lite spec."""
    fit = getattr(sheet.component, "fit", "fill")

    if fit == "fill":
        chart_spec["width"] = sheet.content_width
        chart_spec["height"] = sheet.content_height
    elif fit == "width":
        chart_spec["width"] = sheet.content_width
        # height is the chart's natural height; do not override
        chart_spec.pop("height", None)
    elif fit == "height":
        chart_spec["height"] = sheet.content_height
        # width is the chart's natural width; do not override
        chart_spec.pop("width", None)

    return chart_spec
```

### 10.7 HTML Output Structure

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>{dashboard}</title>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: {theme.font.family.body}; }
    a { text-decoration: none; cursor: pointer; }
    img { display: block; }
  </style>
</head>
<body>
  <div style="width: {canvas.width}px; height: {canvas.height}px; overflow: hidden;">
    <!-- recursively rendered tree — all divs have solved pixel sizes -->
  </div>
  <script>
    const specs = {
      "sheet-kpi_revenue": { /* Vega-Lite JSON with solved width/height */ },
      "sheet-revenue_chart": { /* Vega-Lite JSON with solved width/height */ },
    };
    Object.entries(specs).forEach(([id, spec]) => {
      vegaEmbed(`#${id}`, spec, { actions: false });
    });
  </script>
</body>
</html>
```

---

## 11. Validation Rules

1. **Required:** `dashboard`, `canvas` (with `width`/`height`), `root` (with `type: root`).
2. **Root type:** Must be `"root"`.
3. **Valid types:** `root`, `container`, `sheet`, `text`, `navigation`, `navigation_button`, `navigation_link`, `image`, `blank`.
4. **Contains:** Only `root`/`container` have `contains`. Leaf types must not.
5. **Ref integrity:** String refs in `contains` must resolve to `components` keys or earlier inline-named components.
6. **Unique names:** No duplicate component names across `components` and inline-named definitions.
7. **Style refs:** `style` values must exist in `styles` block.
8. **Sheet links:** `link` paths should point to existing chart YAML files (if filesystem available).
9. **Sizing:** Width/height must be int, `"Npx"`, `"N%"`, `"auto"`, or omitted.
10. **Fit values:** `fit` must be `"fill"`, `"width"`, or `"height"` (sheets only).
11. **Sheet naming (warning):** Anonymous sheets get auto-generated IDs; named preferred.
12. **Solver warnings:** Overconstrained layouts emit warnings but still render (see §8.4).

---

## 12. Pydantic Schema

```python
from __future__ import annotations
from typing import Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

SizeValue = Union[int, str, None]

class StyleProperties(BaseModel):
    background: str | None = None
    border: str | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    border_radius: int | str | None = None
    shadow: str | None = None
    opacity: float | None = Field(None, ge=0.0, le=1.0)
    font_size: int | None = None
    font_weight: str | int | None = None
    font_family: str | None = None
    color: str | None = None
    text_align: Literal["left", "center", "right"] | None = None

class Canvas(BaseModel):
    width: int = 1440
    height: int = 900

class ContainerBase(BaseModel):
    """Shared fields for root and container."""
    model_config = ConfigDict(extra="allow")
    orientation: Literal["horizontal", "vertical"]
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None
    contains: list[Any]

class RootComponent(ContainerBase):
    type: Literal["root"]

class ContainerComponent(ContainerBase):
    type: Literal["container"]

class SheetComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["sheet"]
    link: str
    fit: Literal["fill", "width", "height"] = "fill"
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None

class TextComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["text"]
    content: str
    preset: Literal["title", "subtitle", "heading", "body", "caption", "label"] | None = None
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None

class NavigationBase(BaseModel):
    """Shared fields for all navigation types."""
    model_config = ConfigDict(extra="allow")
    text: str
    link: str
    target: Literal["_self", "_blank"] = "_self"
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None

class NavigationComponent(NavigationBase):
    type: Literal["navigation"]          # alias for navigation_button

class NavigationButtonComponent(NavigationBase):
    type: Literal["navigation_button"]

class NavigationLinkComponent(NavigationBase):
    type: Literal["navigation_link"]

class ImageComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["image"]
    src: str
    alt: str = ""
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None

class BlankComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["blank"]
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None

Component = Union[
    RootComponent, ContainerComponent, SheetComponent, TextComponent,
    NavigationComponent, NavigationButtonComponent, NavigationLinkComponent,
    ImageComponent, BlankComponent,
]

class DashboardSpec(BaseModel):
    dashboard: str
    description: str | None = None
    canvas: Canvas = Canvas()
    styles: dict[str, StyleProperties] | None = None
    components: dict[str, Component] | None = None
    root: RootComponent
```

---

## 13. Future Extensions (Out of Scope for v1)

- **Filter components** with targeting and JS runtime for state management
- **Parameter components** driving chart calculations
- **Cross-chart actions** (click/hover filtering between charts)
- **Collapsible containers** with toggle buttons
- **Tabs** (container variant showing one child at a time)
- **Responsive breakpoints** (multiple canvas sizes)
- **Drag-and-drop editing** (GUI producing Layout DSL YAML)
- **Hover states** on navigation (`button_hover_color`, etc.)
- **Image aspect-ratio-aware sizing** (solver reads intrinsic dimensions from image files)
