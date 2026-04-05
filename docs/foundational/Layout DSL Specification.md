# Layout DSL Specification: Dashboard Composition Grammar

This document defines the Layout DSL — a YAML grammar for composing dashboards as nested containers of static and embedded components. It translates deterministically to fixed-size HTML divs via a layout solver.

Scope: **static layout and navigation only**. Interactive features (filters, parameters, cross-chart actions) are deferred to a future revision.

---

## 1. Design Philosophy

### 1.1 Principles

- **Tableau's dashboard model.** Horizontal and vertical containers nest arbitrarily deep. Anyone who has built a Tableau dashboard recognizes this structure.
- **Type-led syntax.** Every element starts with its type as the YAML key: `horizontal:`, `sheet:`, `text:`. You see *what* something is immediately — no hunting for a `type` field buried in properties.
- **The tree IS the layout.** You read the YAML top-to-bottom and see the dashboard structure directly. The `root` contains list is an outline of the dashboard.
- **Templates for reuse.** The `components` block defines reusable structural templates. Usage sites merge overrides onto the base — same padding and style everywhere, different content in each instance.
- **Fixed canvas.** Dashboards are authored at a fixed pixel size (e.g., 1440×900). No responsive breakpoints in v1.
- **Solver-based sizing.** Users specify sizes in `%`, `px`, or `auto`. A deterministic layout solver resolves every element to concrete pixel dimensions before rendering. The user never thinks about CSS flex algorithms.
- **Border-box model.** An element's specified size is its outer box. Padding shrinks the content area inward. Margins are additional spacing between elements.
- **Gap over margin.** Containers declare `gap` for uniform spacing between children. Per-child margin is available but rarely needed.
- **Shared styles with inline overrides.** A `styles` dictionary defines reusable presets. Components reference by name and override inline. `html` property provides a raw CSS escape hatch that supersedes everything.
- **No interactivity (v1).** Output is static HTML/CSS with Vega-Lite embeds. Navigation between dashboards is the only "interactive" element.
- **Minimal keywords.** Niche CSS properties are handled by the `html` escape hatch rather than dedicated DSL keywords.

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

Chart titles are defined in the Chart DSL and rendered natively by Vega-Lite. The Layout DSL controls visibility via `show_title` on sheets but never duplicates title content.

---

## 2. Document Structure

```yaml
dashboard: "Sales Overview"              # Required: display name
description: "Weekly sales KPIs..."      # Optional
canvas:                                   # Optional (defaults: 1440×900)
  width: 1440
  height: 900

styles:                                   # Optional: reusable style presets
  card:
    background: "#FFFFFF"
    border_radius: 8

components:                               # Optional: predefined reusable components
  revenue_kpi:
    sheet: kpi_revenue.yaml
    style: card

root:                                     # Required: the dashboard layout tree
  orientation: vertical
  padding: 24
  gap: 20
  contains:
    - text: "Sales Overview"
      preset: title
    - horizontal:
        gap: 16
        contains:
          - revenue_kpi                   # Component referred here
          - sheet: orders_kpi.yaml
            style: card
    - horizontal:
        gap: 16
        contains:
          - sheet: revenue.yaml
            style: card
            padding: 12
          - sheet: orders.yaml
            style: card
            padding: 12
```

---

## 3. Type-Led Syntax

Every entry in a `contains` list is a single-key YAML dict where the **key is the type** (or a component template name). The value is either a dict of properties or a shorthand scalar.

### 3.1 Container Types

`horizontal` and `vertical` are the two container types. The type name *is* the orientation — there is no separate `orientation` field.

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

### 3.2 Leaf Types

The type key's value is always the component's primary field. Additional properties appear as sibling keys in the same YAML mapping:

```yaml
- sheet: revenue.yaml                    # link is the value
- sheet: revenue.yaml                    # with extra properties
  fit: width
  show_title: false
  style: card

- text: "Dashboard Title"               # content is the value
- text: "Dashboard Title"
  preset: title

- image: logo.png                        # src is the value
  alt: "Company Logo"
  height: 40

- button: "Export"                        # text is the value
  href: "/export"

- link: "Data Dictionary ↗"              # text is the value
  href: "/docs"
  target: _blank

- blank:                                 # no primary field
- blank:
  height: 16
```

This produces a multi-key YAML dict for each leaf component. The parser identifies the type from the first key that matches a known type, extracts its value as the primary field, and treats remaining keys as properties.

### 3.3 Primary Field Mapping

| Type | Primary field | Value example |
|------|--------------|---------------|
| `sheet` | `link` | `sheet: revenue.yaml` |
| `text` | `content` | `text: "Hello"` |
| `image` | `src` | `image: logo.png` |
| `button` | `text` | `button: "Export"` |
| `link` | `text` | `link: "Details"` |
| `blank` | *(none)* | `blank:` |

### 3.5 Known Types

| Type | Category | Description |
|------|----------|-------------|
| `horizontal` | Container | Arranges children left-to-right |
| `vertical` | Container | Arranges children top-to-bottom |
| `sheet` | Leaf | Embeds a Chart DSL visualization |
| `text` | Leaf | Static text block |
| `button` | Leaf | Navigation button (styled with background) |
| `link` | Leaf | Navigation text link (styled as underlined text) |
| `image` | Leaf | Static image |
| `blank` | Leaf | Empty spacer or decorative divider |

---

## 4. Predefined Components

### 4.1 Defining Components

The `components` block defines fully specified, reusable components. Each entry uses the same type-led syntax as the tree — the component is complete as defined, with no merging or overrides at the usage site:

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

Components can also be containers with full `contains` lists:

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

### 4.2 Using Components

A component is referenced by name in `contains` as a bare string. It is inserted as-is — no overrides, no merging:

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
          - sheet: revenue_trend.yaml
          - sheet: orders_by_region.yaml
```

### 4.3 Resolution Rule

Every `contains` entry is parsed by checking its shape:

```
String?                → look up in components; error if not found
Dict key is a known type  → parse as that type (§3)
Dict key is in components → error (use bare string, not dict)
Key matches neither       → error
```

### 4.4 Constraints

1. **Components cannot reference other components.** A component's definition (including any `contains` list) may only use known types, never other component names. This prevents circular references and keeps components self-contained.

2. **Component names must not shadow known type names.** A component named `horizontal`, `sheet`, `text`, etc. is rejected at parse time.

3. **No overrides at usage.** Components are used as-is. Reference by bare string only. If you need a variation, define a separate component or use inline types directly.

4. **Validation at parse time.** Each component is validated as a complete, structurally valid element when the dashboard is parsed.

### 4.5 Purpose of Components

Components are a **separation of concerns** mechanism. The `components` block is where you define *what things look like* — styling, content, and structure. The `root` tree is where you define *how things are arranged* — position, order, and spatial relationships.

This separation keeps the layout tree scannable: `root` reads as a pure arrangement of named pieces, while all visual details live in `components`. Even elements used only once benefit from this pattern when it improves clarity.

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

---

## 5. The Root

The dashboard's outermost element. There is exactly one per dashboard. It behaves like a `vertical` or `horizontal` container but is constrained to the canvas dimensions.

```yaml
root:
  orientation: vertical          # Required: horizontal | vertical
  padding: 24
  gap: 20
  contains:
    - ...
```

The root does not use type-led syntax — it is always `root:` with an explicit `orientation` field. This is the one exception to the type-led pattern, because the root is a fixed structural element, not a child in a `contains` list.

**Canvas constraint:** The root never exceeds the canvas size. If the root has margin, the margin is subtracted from the canvas dimensions inward.

```
Canvas: 1440 × 900
Root margin: 16 (all sides)
Root padding: 24 (all sides)

Root outer box:  1440 - 32 = 1408 × 900 - 32 = 868
Root content box: 1408 - 48 = 1360 × 868 - 48 = 820

Children are laid out within the 1360 × 820 content box.
```

---

## 6. Component Reference

### 6.1 Containers — `horizontal`, `vertical`

Arrange children along a main axis.

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `contains` | list | Required | Child components |
| `gap` | int | `0` | Pixels between children on main axis |
| `width` | SizeValue | `auto` | Outer box width |
| `height` | SizeValue | `auto` | Outer box height |
| `padding` | spacing | `0` | Inner spacing (CSS shorthand) |
| `margin` | spacing | `0` | Outer spacing (CSS shorthand) |
| `style` | string | — | Reference to shared style |
| `html` | string | — | Raw CSS escape hatch |

All children pack to the start of their container (top-left origin). There are no `align` or `justify` keywords — the solver uses fixed-size inline blocks, not flexbox distribution.

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
      - blank:                          # flex spacer — pushes nav to the right
      - button: "Details →"
          href: "/detail"
```

### 6.2 Sheet (Chart Embed)

Embeds a Chart DSL visualization. Named sheets get stable HTML IDs for vegaEmbed.

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `link` | string | Required | Path to chart YAML file |
| `fit` | `fill` \| `width` \| `height` | `fill` | Chart fitting mode |
| `show_title` | bool | `true` | Whether to show the chart's Vega-Lite title |
| `name` | string | — | Explicit ID for the sheet (auto-generated if omitted) |
| `width` | SizeValue | `auto` | Outer box width |
| `height` | SizeValue | `auto` | Outer box height |
| `padding` | spacing | `0` | Space between card edge and chart |
| `margin` | spacing | `0` | Outer spacing |
| `style` | string | — | Reference to shared style |
| `html` | string | — | Raw CSS escape hatch |

**The `fit` property** controls how the Vega-Lite chart relates to the sheet's solved pixel rect:

| `fit` value | Behavior | Vega-Lite sizing | CSS overflow |
|---|---|---|---|
| `fill` (default) | Chart fills the entire content area | `width` and `height` from solved rect | `overflow: hidden` |
| `width` | Chart scales to content width, scrolls vertically | `width` from solved rect; natural height | `overflow-y: auto` |
| `height` | Chart scales to content height, scrolls horizontally | `height` from solved rect; natural width | `overflow-x: auto` |

**The `show_title` property** controls whether the chart's Vega-Lite title is visible. When `false`, the renderer injects a title override to suppress it. This is useful when the dashboard provides its own section headings and the chart title would be redundant.

```yaml
# Simple — just a chart
- sheet: revenue.yaml

# With extra properties
- sheet: revenue.yaml
  fit: width
  show_title: false
  style: card
  padding: 12
```

### 6.3 Text

Static text blocks. Use `preset` for quick styling.

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `content` | string | Required | The text to display |
| `preset` | preset name | — | Built-in text preset (see table below) |
| `width` | SizeValue | `auto` | Outer box width |
| `height` | SizeValue | `auto` | Outer box height |
| `padding` | spacing | `0` | Inner spacing |
| `margin` | spacing | `0` | Outer spacing |
| `style` | string | — | Reference to shared style |
| `html` | string | — | Raw CSS escape hatch |

**Text presets** (values come from the theme):

| Preset | font_size | font_weight | color | text_align |
|---|---|---|---|---|
| `title` | 24 | bold | theme.text.primary | left |
| `subtitle` | 18 | 600 | theme.text.secondary | left |
| `heading` | 16 | 600 | theme.text.primary | left |
| `body` | 14 | normal | theme.text.primary | left |
| `caption` | 12 | normal | theme.text.tertiary | left |
| `label` | 11 | 500 | theme.text.secondary | left |

**Text overflow:** Text renders with `overflow: hidden`. Content that exceeds solved dimensions is clipped.

```yaml
- text: "Sales Performance Dashboard"
  preset: title

- text: |
    Revenue metrics for Q4 2024.
    All figures in USD thousands.
  preset: caption
```

### 6.4 Navigation — `button`, `link`

Buttons and links for dashboard navigation. Rendered as `<a>` tags with different default styling. The type key's value is the display text (the primary field).

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| *(value)* | string | Required | Button/link display text (primary field) |
| `href` | string | Required | Target URL or dashboard path |
| `target` | `_self` \| `_blank` | `_self` | Link target |
| `width` | SizeValue | `auto` | Outer box width |
| `height` | SizeValue | `auto` | Outer box height |
| `padding` | spacing | `0` | Inner spacing |
| `margin` | spacing | `0` | Outer spacing |
| `style` | string | — | Reference to shared style |
| `html` | string | — | Raw CSS escape hatch |

Note: The URL property is `href` (not `link`) to avoid collision with the `link` type name.

**Default appearance:**

| Type | Background | Text style |
|------|-----------|------------|
| `button` | Solid background, rounded corners, padding | White text |
| `link` | Transparent | Underlined, colored text |

```yaml
- button: "View Details →"
  href: "/dashboards/detail"

- link: "Data Dictionary ↗"
  href: "https://docs.example.com/data"
  target: _blank
```

### 6.5 Image

Static images for logos, decorative graphics, or inline visuals.

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `src` | string | Required | Image file path or URL |
| `alt` | string | `""` | Alt text for accessibility |
| `width` | SizeValue | `auto` | Outer box width |
| `height` | SizeValue | `auto` | Outer box height |
| `padding` | spacing | `0` | Inner spacing |
| `margin` | spacing | `0` | Outer spacing |
| `style` | string | — | Reference to shared style |
| `html` | string | — | Raw CSS escape hatch |

Default `object-fit` is `contain`. Override via `html: "object-fit: cover;"` if needed.

```yaml
- image: logo.svg
  alt: "Company Logo"
  height: 40
  width: 120
```

### 6.6 Blank (Spacer)

Empty div for spacing or decorative dividers. Most spacing should use `gap` on containers — use `blank` for uneven spacing or visual dividers.

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `width` | SizeValue | `auto` | Outer box width |
| `height` | SizeValue | `auto` | Outer box height |
| `padding` | spacing | `0` | Inner spacing |
| `margin` | spacing | `0` | Outer spacing |
| `style` | string | — | Reference to shared style |
| `html` | string | — | Raw CSS escape hatch |

```yaml
# Simple spacer
- blank:
    width: 16

# Flex spacer — pushes siblings apart
- blank:

# Horizontal divider
- blank:
    width: "100%"
    height: 1
    background: "#E0E0E0"
```

---

## 7. Styles System

### 7.1 Defining Shared Styles

```yaml
styles:
  card:
    background: "#FFFFFF"
    border: "1px solid #E0E0E0"
    border_radius: 8
    shadow: "0 1px 3px rgba(0,0,0,0.1)"

  dark_panel:
    background: "#1E293B"
    color: "#FFFFFF"

  header_bar:
    background: "#F8F9FA"
    border_bottom: "1px solid #DEE2E6"
```

### 7.2 Available Style Properties

**Box model:**

| Property | Type | CSS Output |
|---|---|---|
| `background` | string | `background` |
| `border` | string | `border` |
| `border_radius` | int or string | `border-radius` (int → px) |
| `opacity` | float (0–1) | `opacity` |

**Text:**

| Property | Type | CSS Output |
|---|---|---|
| `font_size` | int | `font-size` (→ px) |
| `color` | string | `color` |
| `text_align` | `left` \| `center` \| `right` | `text-align` |

**Advanced:** `border_top`, `border_bottom`, `border_left`, `border_right`, `shadow`, `font_weight`, `font_family`

**Anything else:** Use the `html` escape hatch.

### 7.3 Applying Styles

```yaml
- sheet: revenue.yaml
  style: card                        # shared style
  background: "#F0F8FF"              # inline override (wins over shared)
  html: "transition: all 0.2s;"      # raw CSS (wins everything)
```

### 7.4 Resolution Order

```
theme defaults → text preset → shared style → inline properties → html (wins all)
```

The `html` property is a raw CSS string appended last. It supersedes all other styling for any property it sets.

---

## 8. Sizing Model

### 8.1 Overview

The layout solver resolves every element to concrete pixel dimensions before rendering. The output HTML contains only fixed-size divs — no CSS flex algorithms run in the browser.

```
YAML DSL → Parse → Layout Solver → Resolved pixel tree → HTML (fixed divs)
```

### 8.2 Box Model

Border-box semantics throughout:

- **Size** = outer box (the space an element occupies in its parent)
- **Padding** shrinks the content area inward
- **Margin** is spacing between elements, subtracted from the container's available space
- **Gap** is uniform spacing between children, subtracted from the container's available space

```
┌─── container content box ────────────────────────────────────┐
│                                                              │
│  ┌─ margin ─┐        gap        ┌─ margin ─┐               │
│  │          │         ↕         │          │               │
│  │  ┌──── outer box ────────┐   │  ┌──── outer box ──┐     │
│  │  │                       │   │  │                 │     │
│  │  │  ┌── padding ──────┐  │   │  │  ┌───────────┐  │     │
│  │  │  │                 │  │   │  │  │           │  │     │
│  │  │  │  content area   │  │   │  │  │  content  │  │     │
│  │  │  │                 │  │   │  │  │           │  │     │
│  │  │  └─────────────────┘  │   │  │  └───────────┘  │     │
│  │  │                       │   │  │                 │     │
│  │  └───────────────────────┘   │  └─────────────────┘     │
│  │          │                   │          │               │
│  └──────────┘                   └──────────┘               │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 8.3 Value Formats

| Format | Example | Meaning |
|---|---|---|
| Integer | `300` | 300 pixels |
| Pixel string | `"300px"` | 300 pixels (equivalent to integer) |
| Percentage | `"50%"` | 50% of the container's content box on this axis |
| `"auto"` | `"auto"` | Fill remaining space (shared equally with other `auto` children) |
| Omitted | — | Same as `auto` |

### 8.4 Margin & Padding Shorthand

| DSL Value | Meaning |
|---|---|
| `16` | 16px all sides |
| `"8 16"` | 8px top/bottom, 16px left/right |
| `"8 16 12 16"` | 8px top, 16px right, 12px bottom, 16px left |

---

## 9. Layout Solver Algorithm

The solver walks the dashboard tree top-down, starting from the root. At each node it computes concrete pixel dimensions for all children.

### 9.1 Root Resolution

```
root_outer_width  = canvas.width  - root.margin_left - root.margin_right
root_outer_height = canvas.height - root.margin_top  - root.margin_bottom
root_content_width  = root_outer_width  - root.padding_left - root.padding_right
root_content_height = root_outer_height - root.padding_top  - root.padding_bottom
```

### 9.2 Container Resolution

Given a container with solved `content_W × content_H`, orientation, and `N` children:

**Step 1 — Determine axes.**

Main axis = width (horizontal) or height (vertical). Cross axis = the other.

**Step 2 — Subtract gap and child margins.**

```
total_gap = gap × (N - 1)
total_margin = Σ (child main-axis margins)
distributable = content_main - total_gap - total_margin
```

**Step 3 — Classify children into three buckets.**

| Bucket | Condition | Example |
|---|---|---|
| A: Percentage | Main-axis size is `%` | `width: "60%"` |
| B: Fixed px | Main-axis size is int or `"Npx"` | `width: 300` |
| C: Auto | Main-axis size is `auto` or omitted | *(default)* |

**Step 4 — Resolve sizes in priority order.**

Percentages resolve against the **content box** (pre-gap, pre-margin):

```
resolved_A = Σ (percentage × content_main)   for Bucket A
resolved_B = Σ (fixed_px_value)              for Bucket B
total_claimed = resolved_A + resolved_B
```

**Case 1: Everything fits** (`total_claimed ≤ distributable`):

- Bucket A and B get their resolved sizes
- Remaining space is divided equally among Bucket C children
- If no Bucket C children, remaining space is empty (start-aligned packing)

**Case 2: Overconstrained** (`total_claimed > distributable`):

1. If `resolved_A ≤ distributable`: Percentages honored. Fixed-px children share the remaining space proportionally. Auto children get 0px.
2. If `resolved_A > distributable`: All children shrunk proportionally to fit. Solver emits a warning.

**Step 5 — Cross-axis resolution.**

Default: 100% of container's cross-axis content, minus cross-axis margins. Explicit values override.

**Step 6 — Content areas.**

```
content_W = outer_W - padding_left - padding_right
content_H = outer_H - padding_top - padding_bottom
```

Clamped to 0 minimum.

**Step 7 — Recurse** into any child that is a container.

### 9.3 Worked Example

```yaml
canvas: { width: 1440, height: 900 }

root:
  orientation: vertical
  padding: 24
  gap: 16
  contains:
    - horizontal:
        height: 56
        padding: "0 16"
        gap: 12
        contains:
          - image: logo.svg
            width: 120
            height: 28
          - text: "Dashboard"
            preset: title
          - blank:
          - button: "Details →"
              href: "/detail"
              width: 140
              padding: "6 16"
    - horizontal:
        padding: 16
        gap: 16
        contains:
          - sheet: revenue.yaml
            width: "60%"
            padding: 16
          - sheet: orders.yaml
            padding: 16
```

**Solver trace:**

```
ROOT
  canvas:          1440 × 900
  root padding:    24 (all sides)
  root content:    1392 × 852

HEADER (vertical child, height: 56)
  main-axis: explicit 56px → outer_H = 56
  cross-axis: 100% → outer_W = 1392
  padding: 0 16 → content: 1360 × 56

  HEADER CHILDREN (horizontal, gap: 12)
    Gap: 12 × 3 = 36
    Margins: 0
    Distributable: 1360 - 36 = 1324

    Bucket B (fixed): logo=120, nav=140 → 260
    Bucket C (auto): text, blank
    Remaining: 1324 - 260 = 1064 → 532 each

    logo:   120 × 56
    text:   532 × 56
    blank:  532 × 56
    nav:    140 × 56, content: 108 × 44 (padding 6 16)

CHART ROW (vertical child, auto height)
  Gap between root children: 16
  Root distributable: 852, header=56, gap=16
  Remaining: 852 - 56 - 16 = 780 → chart_row outer_H = 780
  cross-axis: 1392
  padding: 16 → content: 1360 × 748

  CHART ROW CHILDREN (horizontal, gap: 16)
    Gap: 16 × 1 = 16
    Margins: 0
    Distributable: 1360 - 16 = 1344

    Bucket A: revenue = 60% of 1360 = 816
    Bucket C: orders
    Remaining: 1344 - 816 = 528

    revenue: 816 × 748, content: 784 × 716 (padding 16)
    orders:  528 × 748, content: 496 × 716 (padding 16)

Vega-Lite specs receive:
  revenue.yaml → width: 784, height: 716
  orders.yaml  → width: 496, height: 716
```

### 9.4 Solver Warnings

The solver emits warnings (never errors) for constraint violations. The dashboard still renders.

| Condition | Solver behavior |
|---|---|
| Fixed + % sizes exceed distributable space | Shrink fixed-px proportionally after honoring percentages |
| Percentages alone exceed space | Shrink all children proportionally |
| Auto child receives 0px | Warn; child renders invisible |
| Padding exceeds outer box | Content area clamped to 0 |

---

## 10. Child Resolution Algorithm

The resolver is the core of the parsing pipeline. It transforms raw YAML `contains` entries into typed component objects.

### 10.1 Resolution Flow

```
contains entry
  │
  ├─ String?
  │   YES ─→ Look up in components dict
  │          Return the predefined component as-is
  │          Error if not found
  │
  ├─ Dict: multi-key with a known type key?
  │   YES ─→ Extract type key's value as primary field
  │          Remaining keys are properties
  │          Parse as that type (leaf component)
  │
  └─ Dict: single-key, key is a known type?
      YES ─→ Value is a dict of properties
             Parse as that type (container component)
```

Bare strings are always component references. Leaf components (sheet, text, image, button, link, blank) produce multi-key dicts because the type key carries the primary value and extra properties are siblings. Container components (horizontal, vertical) produce single-key dicts because their properties are nested.

### 10.2 Validation

1. **Component names must not shadow known type names.** Rejected at parse time.
2. **Components cannot reference other components.** A component's `contains` may only use known types.
3. **Component references take no overrides.** The value must be null.
4. **Style references must exist.** The `style` field must reference a key in the `styles` block.
5. **Size values must be valid.** Integer, `"Npx"`, `"N%"`, `"auto"`, or omitted.

---

## 11. Translation Rules

### 11.1 Pipeline

```
YAML DSL
  → Parse (DashboardSpec — resolve component refs, validate)
  → Layout Solver (produces ResolvedTree with pixel rects)
  → HTML Renderer (fixed-size divs + vegaEmbed)
```

### 11.2 Component → HTML

| Type | HTML | Key behavior |
|---|---|---|
| `horizontal` / `vertical` | `<div>` | Fixed-size, children arranged by orientation |
| `sheet` | `<div>` | Fixed-size, `id` for vegaEmbed, overflow from `fit` |
| `text` | `<div>` | Fixed-size, text content, `overflow: hidden` |
| `button` | `<a>` | Button styling, `href` from `link` |
| `link` | `<a>` | Link styling, `href` from `link` |
| `image` | `<img>` | Fixed-size, `object-fit: contain` |
| `blank` | `<div>` | Fixed-size, empty |

### 11.3 Sheet `show_title` Implementation

When `show_title: false`, the renderer suppresses the Vega-Lite title by injecting a config override into the embed:

```javascript
vegaEmbed('#sheet-id', {
  ...spec,
  title: null
}, { actions: false });
```

When `show_title: true` (default), the spec is embedded as-is and the chart's own title renders.

### 11.4 Vega-Lite Embedding

The solver resolves sheet dimensions before rendering. Vega-Lite specs receive explicit pixel sizes — no `container` sizing mode, no ResizeObserver.

```python
def embed_spec(sheet: ResolvedNode, chart_spec: dict) -> dict:
    fit = sheet.component.fit  # "fill", "width", or "height"
    if fit == "fill":
        chart_spec["width"] = sheet.content_width
        chart_spec["height"] = sheet.content_height
    elif fit == "width":
        chart_spec["width"] = sheet.content_width
        chart_spec.pop("height", None)
    elif fit == "height":
        chart_spec["height"] = sheet.content_height
        chart_spec.pop("width", None)
    return chart_spec
```

### 11.5 HTML Output Structure

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
      "sheet-revenue": { /* Vega-Lite JSON with solved width/height */ },
      "sheet-orders": { /* Vega-Lite JSON with solved width/height */ },
    };
    Object.entries(specs).forEach(([id, spec]) => {
      vegaEmbed(`#${id}`, spec, { actions: false });
    });
  </script>
</body>
</html>
```

---

## 12. Style Resolution

```
theme defaults → navigation type defaults → text preset → shared style → inline properties → html (wins all)
```

### 12.1 Resolution Layers

1. **Structural CSS** — display, overflow, sizing from solver
2. **Theme defaults** — font-family for text-bearing components
3. **Navigation type defaults** — button gets background/padding/border-radius; link gets underline/color
4. **Text preset** — font-size, font-weight, color from theme preset definitions
5. **Shared style** — all non-null properties from the referenced `styles` entry
6. **Inline overrides** — properties set directly on the component (via extra fields)
7. **Margin/padding** — from the component's fields
8. **`html` escape hatch** — raw CSS string appended last, wins everything

---

## 13. Complete Examples

### 13.1 Executive Dashboard

```yaml
dashboard: "Sales Overview"
canvas: { width: 1440, height: 900 }

styles:
  card:
    background: "#FFFFFF"
    border_radius: 8
    shadow: "0 1px 3px rgba(0,0,0,0.1)"

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
    # Header
    - horizontal:
        height: 56
        gap: 12
        contains:
          - image: logo.svg
            height: 28
            width: 100
          - text: "Sales Overview"
            preset: title
          - blank:
          - button: "Detailed Report →"
              href: "/dashboards/detail"

    # KPI Row
    - horizontal:
        height: 120
        gap: 16
        contains:
          - kpi_revenue
          - kpi_orders
          - kpi_arpu
          - kpi_customers

    # Charts
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

### 13.2 Sidebar Navigation Dashboard

```yaml
dashboard: "Executive Summary"
canvas: { width: 1440, height: 900 }

styles:
  card:
    background: "#FFFFFF"
    border_radius: 8
    shadow: "0 1px 3px rgba(0,0,0,0.1)"
  sidebar:
    background: "#1E293B"

root:
  orientation: horizontal
  contains:
    # Sidebar
    - vertical:
        width: 220
        style: sidebar
        padding: "24 16"
        gap: 8
        contains:
          - image: logo_white.svg
            height: 24
            width: 100
          - blank:
              height: 16
          - button: "Overview"
              href: "/overview"
          - button: "Sales"
              href: "/sales"
          - button: "Customers"
              href: "/customers"

    # Main content
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
                  padding: 16
                - sheet: revenue_by_region.yaml
                  style: card
                  padding: 16

          - sheet: order_details.yaml
            style: card
            padding: 16
```

### 13.3 Sectioned Report

```yaml
dashboard: "Operations Dashboard"
canvas: { width: 1440, height: 1200 }

styles:
  card:
    background: "#FFFFFF"
    border_radius: 8
    shadow: "0 1px 3px rgba(0,0,0,0.1)"

root:
  orientation: vertical
  padding: 24
  gap: 24
  contains:
    - text: "Operations Dashboard"
      preset: title

    # Overview section
    - vertical:
        gap: 12
        contains:
          - text: "Overview"
            preset: subtitle
          - horizontal:
              gap: 16
              contains:
                - sheet: throughput.yaml
                  style: card
                  padding: 12
                - sheet: error_rate.yaml
                  style: card
                  padding: 12

    # Regional section
    - vertical:
        gap: 12
        contains:
          - text: "Regional Breakdown"
            preset: subtitle
          - sheet: region_map.yaml
            style: card
            padding: 12

    # Queue details section
    - vertical:
        gap: 12
        contains:
          - text: "Queue Details"
            preset: subtitle
          - horizontal:
              gap: 16
              contains:
                - sheet: queue_a.yaml
                  style: card
                  padding: 12
                - sheet: queue_b.yaml
                  style: card
                  padding: 12
                - sheet: queue_c.yaml
                  style: card
                  padding: 12
```

---

## 14. Validation Rules

1. **Required fields:** `dashboard`, `root` (with `orientation` and `contains`).
2. **Canvas:** Optional, defaults to 1440×900.
3. **Known types:** `horizontal`, `vertical`, `sheet`, `text`, `button`, `link`, `image`, `blank`.
4. **Contains:** Only containers (`horizontal`, `vertical`) have `contains`. Leaf types must not.
5. **Component names:** Must not shadow known type names.
6. **Component isolation:** Components cannot reference other component names in their `contains`.
7. **Component usage:** Component references are bare strings (not dicts).
8. **Style refs:** `style` values must exist in `styles` block.
9. **Sizing:** Width/height must be int, `"Npx"`, `"N%"`, `"auto"`, or omitted.
10. **Fit values:** `fit` must be `"fill"`, `"width"`, or `"height"` (sheets only).
11. **Solver warnings:** Overconstrained layouts emit warnings but still render (see §9.4).

---

## 15. Future Extensions (Out of Scope for v1)

- **Filter components** with targeting and JS runtime
- **Parameter components** driving chart calculations
- **Cross-chart actions** (click/hover filtering between charts)
- **Collapsible containers** with toggle buttons
- **Tabs** (container variant showing one child at a time)
- **Responsive breakpoints** (multiple canvas sizes)
- **Drag-and-drop editing** (GUI producing Layout DSL YAML)
- **Ratio-based sizing** (`sizes: [1, 2, 1]` on containers)
- **Component templates with merge** (override properties at usage site)
- **Image aspect-ratio-aware sizing** (solver reads intrinsic dimensions)
