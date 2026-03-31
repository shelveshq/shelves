# KPI Pattern Specification

**Status:** Draft
**Scope:** Chart DSL extension — redesigns the `kpi` top-level property for rendering KPI / Big Number cards as Vega-Lite `vconcat` specs.
**Depends on:** Phase 1 (single-measure chart pipeline working), Theme layer (default theme loaded)
**Replaces:** The existing `KPIConfig` / `KPIComparison` models in `chart_schema.py` (which are parsed but have no translator support)

---

## 1. Design Rationale

### 1.1 The Problem

KPI cards (BANs — Big Ass Numbers) are the most common dashboard component. Every executive dashboard has a row of them. Yet in Tableau, producing a polished KPI card requires creating 3–4 calculated fields (current period value, prior period value, delta, delta sign), formatting each independently, composing multiple worksheets into a dashboard container, and manually styling fonts, colors, and alignment. For four KPIs, that's 8–16 worksheets and a dozen calculated fields.

Power BI's Card visual solves this with a rigid, opinionated component — fast to create, but inflexible. Neither extreme is acceptable.

### 1.2 The Charter Approach

Charter treats KPI cards as a **Chart DSL pattern** — each KPI is a chart YAML file with a `kpi` property block that triggers a dedicated rendering path. The `kpi` block is a structured shorthand that handles value display, number formatting, comparison computation (delta), and polarity-based coloring.

**Key design decisions:**

- **KPIs are chart specs, not layout components.** They live in chart YAML files, are referenced from the Layout DSL via `type: sheet`, and are version-controlled like any other chart. This preserves the clean separation: Chart DSL = what, Layout DSL = where, Theme = how.
- **Comparison logic belongs in the semantic layer.** The `kpi` block does not compute period-over-period values. It expects pre-computed comparison measures from Cube.dev (or equivalent). The only arithmetic the renderer performs is the delta between the two values it receives (`delta_percent`, `delta_absolute`). This avoids building a time-intelligence engine inside the translator.
- **The renderer produces Vega-Lite, like every other pattern.** The KPI pattern compiles to a Vega-Lite `vconcat` spec with `text` marks — one sub-spec per visual row (title, value, comparison). This keeps the rendering pipeline uniform: every pattern produces a dict, theme merges via `merge_theme()`, data binds via `bind_data()`, and `vegaEmbed()` renders it. No HTML escape hatch needed.
- **No sparklines in v1.** Sparklines rarely communicate actionable insight and add significant rendering complexity. If demand surfaces, a `sparkline` property can be added later as a backward-compatible extension.

### 1.3 Vega-Lite Rendering Approach

The KPI card is rendered as a `vconcat` of 2–3 text mark sub-specs (title, value, optional comparison). Each sub-spec has `height: 1` — Vega-Lite text marks overflow their container without clipping, so the `height` value is effectively irrelevant. The `spacing` property on the `vconcat` controls the vertical gap between rows. This was validated through prototyping across font sizes from 10px to 60px and multiple font families (DejaVu Sans, DejaVu Serif, Poppins, Lora, monospace) — the approach is robust and requires no font-dependent height calculations.

All text is left-aligned via `x: {value: 0}` and `align: "left"`, `baseline: "middle"`.

---

## 2. DSL Grammar

### 2.1 Top-Level Property: `kpi`

The `kpi` property is a **top-level Chart DSL property**. Its presence triggers the KPI rendering pattern. When `kpi` is present, `cols`, `rows`, and `marks` are ignored — the `kpi` block fully describes the rendering intent.

```yaml
# Top-level properties
sheet: <string>          # Display name (also used as default KPI title)
description: <string>    # Optional
data: <string>           # Model name — references a DataModel manifest in models/
kpi: <kpi_block>         # KPI rendering configuration — triggers KPI pattern
filters: <filter_list>   # Optional — same as any chart spec
```

### 2.2 The `kpi` Block

```yaml
kpi:
  value: <string>                     # Required: field name for the primary metric
  format: <string>                    # Required: display format (e.g., "$,.0f", "0.0%")
  title: <string>                     # Optional: display title (defaults to sheet name)
  spacing: <integer>                  # Optional: vertical gap between text rows in px (default from theme)

  comparison:                         # Optional: comparison display block
    field: <string>                   # Required (within comparison): field name for comparison value
    mode: <enum>                      # Optional: delta_percent | delta_absolute | value
    format: <string>                  # Optional: display format override for the comparison
    label: <string>                   # Optional: text label displayed after the comparison value
    polarity: <enum>                  # Optional: up_is_good | down_is_good | neutral
```

### 2.3 Property Reference

#### `kpi.value` — Primary Metric Field

- **Required.** The field name from `data` model's measures whose value is displayed as the big number.
- The translator uses the ModelResolver to validate the field exists and is a measure.
- The renderer reads the first (and typically only) row of query results and extracts this field.

#### `kpi.format` — Value Display Format

- **Required.** Determines how the primary value is formatted for display.
- Uses d3-format syntax passed to Vega-Lite's `format` property:

| Format String | Input | Output | Notes |
|---|---|---|---|
| `"$,.0f"` | 1234567.89 | $1,234,568 | Currency, no decimals |
| `"$,.2f"` | 1234567.89 | $1,234,567.89 | Currency, 2 decimals |
| `",.0f"` | 1234567 | 1,234,567 | Number with commas |
| `"0.0%"` | 0.156 | 15.6% | Percentage |
| `"$,.1s"` | 1234567 | $1.2M | SI prefix (compact) |

#### `kpi.title` — Display Title

- **Optional.** The label shown above the big number (e.g., "Revenue", "Active Users").
- Defaults to the `sheet` property value if omitted.

#### `kpi.spacing` — Vertical Gap Between Rows

- **Optional.** Integer pixel value controlling the `spacing` property on the Vega-Lite `vconcat`.
- Defaults to the theme's `kpi.spacing` value (default: `4`).
- Allows per-card density control: `0` for ultra-compact, `8` for spacious.

#### `kpi.comparison` — Comparison Block

The entire `comparison` block is optional. When omitted, the KPI card renders only the title and big number (2-row vconcat).

#### `kpi.comparison.field` — Comparison Metric Field

- **Required within `comparison`.** A measure field name from the data model.
- Should contain the *prior period value* (for delta modes) or the *raw comparison value* (for `value` mode).
- The semantic layer (Cube.dev) is responsible for computing this value.

#### `kpi.comparison.mode` — Comparison Display Mode

- **Optional.** Default: `delta_percent`.
- Controls what arithmetic the translator generates as Vega-Lite `calculate` transforms:

| Mode | Vega-Lite Transform | Typical Display | Use Case |
|---|---|---|---|
| `delta_percent` | `(value - field) / abs(field)` | ▲ 9.1% | Period-over-period % change |
| `delta_absolute` | `value - field` | ▲ $109,091 | Absolute change vs prior |
| `value` | `format(field, fmt) + label` | $3,000,000 Target | Show a reference value as-is |

**Division by zero:** When `field` is 0 and mode is `delta_percent`, the transform produces `null` via a Vega-Lite conditional expression. The text mark renders nothing for null values — the comparison row is effectively hidden.

#### `kpi.comparison.format` — Comparison Display Format

- **Optional.** Overrides the format used in the Vega-Lite `format()` expression.
- Defaults depend on mode:
  - `delta_percent`: `".1%"` (percentage, 1 decimal)
  - `delta_absolute`: inherits `kpi.format`
  - `value`: inherits `kpi.format`

#### `kpi.comparison.label` — Comparison Label Text

- **Optional.** A text string appended to the formatted comparison value in the `calculate` expression.
- Examples: `"vs. Prior Month"`, `"MoM"`, `"Target"`.
- When omitted, only the formatted comparison value and indicator are shown.

#### `kpi.comparison.polarity` — Directional Coloring

- **Optional.** Default: `up_is_good`.
- Controls the Vega-Lite conditional color encoding on the comparison text mark:

| Polarity | Positive Delta | Negative Delta | Use Case |
|---|---|---|---|
| `up_is_good` | Positive accent (green) | Negative accent (red) | Revenue, users, conversion |
| `down_is_good` | Negative accent (red) | Positive accent (green) | Cost, churn, bounce rate |
| `neutral` | Neutral color | Neutral color | Informational comparisons |

- The actual color values come from the theme's `kpi.semantic` tokens.
- The delta indicator (▲/▼) is generated by a `calculate` transform:
  - Positive delta → ▲
  - Negative delta → ▼
  - Zero delta or `mode: value` → no indicator, neutral color

---

## 3. Pydantic Schema

Replaces the existing `KPIConfig` and `KPIComparison` models in `chart_schema.py`:

```python
class KPIComparison(BaseModel):
    """Configuration for the comparison value displayed beneath the primary KPI metric."""

    field: str                          # Semantic layer measure name for comparison value
    mode: Literal[
        "delta_percent",
        "delta_absolute",
        "value",
    ] = "delta_percent"
    format: str | None = None           # Override format string; defaults per mode
    label: str | None = None            # Text label after comparison value
    polarity: Literal[
        "up_is_good",
        "down_is_good",
        "neutral",
    ] = "up_is_good"


class KPIBlock(BaseModel):
    """
    Top-level `kpi` property on a chart spec.

    When present, the translator routes to the KPI pattern compiler
    which produces a Vega-Lite vconcat of text marks.
    """

    value: str                          # Semantic layer measure name for primary metric
    format: str                         # Display format for the primary value
    title: str | None = None            # Display title; defaults to sheet name
    spacing: int | None = None          # Vertical gap in px; defaults to theme kpi.spacing
    comparison: KPIComparison | None = None
```

**Integration with `ChartSpec`:**

The existing `kpi: KPIConfig | None` field on `ChartSpec` is replaced with `kpi: KPIBlock | None`. The existing `single_measure_requires_marks` validator already exempts specs where `kpi` is set.

**New validator:**

```python
@model_validator(mode="after")
def kpi_excludes_shelf_properties(self) -> "ChartSpec":
    """When kpi is set, cols/rows/marks are ignored. Warn if present."""
    if self.kpi is not None:
        if self.cols is not None or self.rows is not None or self.marks is not None:
            import warnings
            warnings.warn(
                "KPI spec has cols/rows/marks set — these are ignored when kpi is present.",
                UserWarning,
                stacklevel=2,
            )
    return self
```

**Validation rules:**

1. `kpi.value` must exist as a measure in the data model (validated at translation time by ModelResolver).
2. If `comparison` is set, `comparison.field` must also exist as a measure in the data model.
3. `kpi.value` and `comparison.field` must be different fields.
4. `format` must be a non-empty string.

---

## 4. Theme Integration

### 4.1 New Theme Tokens

The KPI pattern introduces **semantic color tokens** and **KPI typography tokens** to the theme layer.

**Semantic color tokens** (reusable beyond KPIs for any directional coloring):

| Figma Token Path | Description | Default Value |
|---|---|---|
| `color.semantic.positive` | Color for favorable change | `#16A34A` (green-600) |
| `color.semantic.negative` | Color for unfavorable change | `#DC2626` (red-600) |
| `color.semantic.neutral` | Color for non-directional comparison | `#6B7280` (gray-500) |

**KPI typography tokens:**

| Figma Token Path | Description | Default Value |
|---|---|---|
| `font.size.kpi.title` | Font size for the KPI title | `13` (px) |
| `font.size.kpi.value` | Font size for the big number | `36` (px) |
| `font.size.kpi.comparison` | Font size for the comparison line | `12` (px) |
| `font.weight.kpi.title` | Font weight for the KPI title | `500` (medium) |
| `font.weight.kpi.value` | Font weight for the big number | `600` (semibold) |
| `font.weight.kpi.comparison` | Font weight for the comparison line | `400` (normal) |

**KPI layout token:**

| Figma Token Path | Description | Default Value |
|---|---|---|
| `spacing.kpi` | Vertical gap between text rows | `4` (px) |

### 4.2 Default Theme Addition

The `default_theme.json` gains a new `kpi` section:

```json
{
  "kpi": {
    "title": {
      "fontSize": 13,
      "fontWeight": 500,
      "color": "#666666"
    },
    "value": {
      "fontSize": 36,
      "fontWeight": 600,
      "color": "#1a1a1a"
    },
    "comparison": {
      "fontSize": 12,
      "fontWeight": 400
    },
    "semantic": {
      "positive": "#16A34A",
      "negative": "#DC2626",
      "neutral": "#6B7280"
    },
    "spacing": 4
  }
}
```

Font family is inherited from the existing theme's `title.font` / `axis.labelFont` — KPIs don't define their own font family, keeping the theme consistent.

### 4.3 Polarity → Vega-Lite Conditional Color

The translator generates a Vega-Lite conditional color encoding based on polarity:

| Polarity | Vega-Lite `condition.test` for favorable color |
|---|---|
| `up_is_good` | `"datum.delta >= 0"` |
| `down_is_good` | `"datum.delta <= 0"` |
| `neutral` | N/A — fixed color value, no condition |

The favorable color uses `theme.kpi.semantic.positive`, unfavorable uses `theme.kpi.semantic.negative`, and neutral/zero uses `theme.kpi.semantic.neutral`.

---

## 5. Translation Rules

### 5.1 Pattern Detection

The KPI pattern is detected by the presence of the `kpi` top-level property on the parsed `ChartSpec`. It takes priority over all other pattern detection.

```python
# In translate.py (pattern router)
def translate_chart(spec: ChartSpec, models_dir=None) -> VegaLiteSpec:
    model = load_model(spec.data, models_dir=models_dir)
    resolver = ModelResolver(model)

    if spec.kpi is not None:
        inner = compile_kpi(spec, resolver)
    elif isinstance(spec.rows, list) or isinstance(spec.cols, list):
        inner = compile_stacked(spec, resolver)
    else:
        inner = compile_single(spec, resolver)

    top_level = apply_facet(inner, spec.facet)
    top_level["$schema"] = VEGA_LITE_SCHEMA
    return top_level
```

### 5.2 Data Expectations

The KPI pattern expects query results with **exactly one row**. The `data` block must reference a model whose measures include `kpi.value` and (if comparison is set) `kpi.comparison.field`.

If the query returns multiple rows, the first row is used (Vega-Lite text marks naturally display the first datum). If the query returns zero rows, the KPI displays nothing (empty chart).

### 5.3 Vega-Lite Output Structure

The KPI translator produces a `vconcat` spec. Each row is a minimal sub-spec with a `text` mark and `x: {value: 0}` for left-alignment.

**Two-row output (no comparison):**

```json
{
  "vconcat": [
    { /* title text mark */ },
    { /* value text mark */ }
  ],
  "spacing": 4,
  "config": {
    "view": {"stroke": null},
    "concat": {"spacing": 4}
  }
}
```

**Three-row output (with comparison):**

```json
{
  "transform": [ /* delta, indicator, comparison_text calculate transforms */ ],
  "vconcat": [
    { /* title text mark */ },
    { /* value text mark */ },
    { /* comparison text mark with conditional color */ }
  ],
  "spacing": 4,
  "config": {
    "view": {"stroke": null},
    "concat": {"spacing": 4}
  }
}
```

### 5.4 Compilation Logic

```python
def compile_kpi(spec: ChartSpec, resolver: FieldTypeResolver) -> VegaLiteSpec:
    """Compile a KPI ChartSpec into a Vega-Lite vconcat of text marks."""

    kpi = spec.kpi
    theme_kpi = _load_kpi_theme()  # from default_theme.json["kpi"]

    title_text = kpi.title or spec.sheet
    spacing = kpi.spacing if kpi.spacing is not None else theme_kpi["spacing"]

    # ── Title row ──
    title_row = {
        "mark": {
            "type": "text",
            "fontSize": theme_kpi["title"]["fontSize"],
            "fontWeight": theme_kpi["title"]["fontWeight"],
            "color": theme_kpi["title"]["color"],
            "align": "left",
            "baseline": "middle",
        },
        "encoding": {"text": {"value": title_text}, "x": {"value": 0}},
        "height": 1,
    }

    # ── Value row ──
    value_row = {
        "mark": {
            "type": "text",
            "fontSize": theme_kpi["value"]["fontSize"],
            "fontWeight": theme_kpi["value"]["fontWeight"],
            "color": theme_kpi["value"]["color"],
            "align": "left",
            "baseline": "middle",
        },
        "encoding": {
            "text": {"field": kpi.value, "type": "quantitative", "format": kpi.format},
            "x": {"value": 0},
        },
        "height": 1,
    }

    rows = [title_row, value_row]
    transforms = []

    # ── Comparison row (optional) ──
    if kpi.comparison is not None:
        comp_transforms, comp_row = _build_comparison(kpi.value, kpi.comparison, theme_kpi)
        transforms = comp_transforms
        rows.append(comp_row)

    # ── Filters (standard DSL filters apply) ──
    filter_transforms = build_transforms(spec.filters, resolver)

    result: VegaLiteSpec = {
        "vconcat": rows,
        "spacing": spacing,
        "config": {"view": {"stroke": None}, "concat": {"spacing": spacing}},
    }

    all_transforms = filter_transforms + transforms
    if all_transforms:
        result["transform"] = all_transforms

    return result
```

### 5.5 Comparison Transform Generation

For `delta_percent` and `delta_absolute` modes, the translator generates `calculate` transforms:

```python
def _build_comparison(value_field, comp, theme_kpi):
    """Build transforms and comparison row for a KPI comparison block."""

    transforms = []
    semantic = theme_kpi["semantic"]

    if comp.mode == "delta_percent":
        fmt = comp.format or ".1%"
        transforms = [
            {
                "calculate": (
                    f"abs(datum.{comp.field}) > 0 "
                    f"? (datum.{value_field} - datum.{comp.field}) / abs(datum.{comp.field}) "
                    f": null"
                ),
                "as": "delta",
            },
            {"calculate": "datum.delta != null ? (datum.delta >= 0 ? '▲' : '▼') : null", "as": "indicator"},
            {"calculate": _comparison_text_expr("indicator", "delta", fmt, comp.label), "as": "comparison_text"},
        ]

    elif comp.mode == "delta_absolute":
        fmt = comp.format or None  # resolved at generation time from kpi.format
        transforms = [
            {"calculate": f"datum.{value_field} - datum.{comp.field}", "as": "delta"},
            {"calculate": "datum.delta >= 0 ? '▲' : '▼'", "as": "indicator"},
            {"calculate": _comparison_text_expr("indicator", "delta", fmt, comp.label), "as": "comparison_text"},
        ]

    elif comp.mode == "value":
        fmt = comp.format or None
        label_suffix = f" + '  {comp.label}'" if comp.label else ""
        transforms = [
            {"calculate": f"format(datum.{comp.field}, '{fmt}'){label_suffix}", "as": "comparison_text"},
        ]

    # Build comparison row with conditional color
    if comp.polarity == "neutral" or comp.mode == "value":
        color_enc = {"value": semantic["neutral"]}
    elif comp.polarity == "down_is_good":
        color_enc = {
            "condition": {"test": "datum.delta <= 0", "value": semantic["positive"]},
            "value": semantic["negative"],
        }
    else:  # up_is_good (default)
        color_enc = {
            "condition": {"test": "datum.delta >= 0", "value": semantic["positive"]},
            "value": semantic["negative"],
        }

    comp_row = {
        "mark": {
            "type": "text",
            "fontSize": theme_kpi["comparison"]["fontSize"],
            "fontWeight": theme_kpi["comparison"]["fontWeight"],
            "align": "left",
            "baseline": "middle",
        },
        "encoding": {
            "text": {"field": "comparison_text", "type": "nominal"},
            "x": {"value": 0},
            "color": color_enc,
        },
        "height": 1,
    }

    return transforms, comp_row


def _comparison_text_expr(indicator_field, delta_field, fmt, label):
    """Build a Vega-Lite calculate expression for comparison display string."""
    label_suffix = f" + '  {label}'" if label else ""
    return f"datum.{indicator_field} + ' ' + format(abs(datum.{delta_field}), '{fmt}'){label_suffix}"
```

---

## 6. Complete Examples

### Example 1: Simple KPI — No Comparison

**DSL Input:**

```yaml
sheet: "Total Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
```

**Vega-Lite Output:**

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "vconcat": [
    {
      "mark": {
        "type": "text", "fontSize": 13, "fontWeight": 500,
        "color": "#666666", "align": "left", "baseline": "middle"
      },
      "encoding": {"text": {"value": "Total Revenue"}, "x": {"value": 0}},
      "height": 1
    },
    {
      "mark": {
        "type": "text", "fontSize": 36, "fontWeight": 600,
        "color": "#1a1a1a", "align": "left", "baseline": "middle"
      },
      "encoding": {
        "text": {"field": "revenue", "type": "quantitative", "format": "$,.0f"},
        "x": {"value": 0}
      },
      "height": 1
    }
  ],
  "spacing": 4,
  "config": {"view": {"stroke": null}, "concat": {"spacing": 4}}
}
```

### Example 2: KPI with Percentage Delta

**DSL Input:**

```yaml
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  title: "Revenue"
  comparison:
    field: revenue_prior_month
    mode: delta_percent
    label: "vs. Prior Month"
    polarity: up_is_good
```

**Vega-Lite Output:**

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "transform": [
    {
      "calculate": "abs(datum.revenue_prior_month) > 0 ? (datum.revenue - datum.revenue_prior_month) / abs(datum.revenue_prior_month) : null",
      "as": "delta"
    },
    {"calculate": "datum.delta != null ? (datum.delta >= 0 ? '▲' : '▼') : null", "as": "indicator"},
    {
      "calculate": "datum.indicator + ' ' + format(abs(datum.delta), '.1%') + '  vs. Prior Month'",
      "as": "comparison_text"
    }
  ],
  "vconcat": [
    {
      "mark": {"type": "text", "fontSize": 13, "fontWeight": 500, "color": "#666666", "align": "left", "baseline": "middle"},
      "encoding": {"text": {"value": "Revenue"}, "x": {"value": 0}},
      "height": 1
    },
    {
      "mark": {"type": "text", "fontSize": 36, "fontWeight": 600, "color": "#1a1a1a", "align": "left", "baseline": "middle"},
      "encoding": {"text": {"field": "revenue", "type": "quantitative", "format": "$,.0f"}, "x": {"value": 0}},
      "height": 1
    },
    {
      "mark": {"type": "text", "fontSize": 12, "fontWeight": 400, "align": "left", "baseline": "middle"},
      "encoding": {
        "text": {"field": "comparison_text", "type": "nominal"},
        "x": {"value": 0},
        "color": {
          "condition": {"test": "datum.delta >= 0", "value": "#16A34A"},
          "value": "#DC2626"
        }
      },
      "height": 1
    }
  ],
  "spacing": 4,
  "config": {"view": {"stroke": null}, "concat": {"spacing": 4}}
}
```

### Example 3: KPI with Absolute Delta — down_is_good

**DSL Input:**

```yaml
sheet: "Operating Cost"
data: finance
kpi:
  value: operating_cost
  format: "$,.0f"
  comparison:
    field: operating_cost_prior_month
    mode: delta_absolute
    label: "vs. Prior Month"
    polarity: down_is_good
```

The polarity condition flips: `"datum.delta <= 0"` maps to the positive (green) color.

### Example 4: KPI with Target (Value Mode)

**DSL Input:**

```yaml
sheet: "Q1 Revenue"
data: orders
kpi:
  value: revenue_qtd
  format: "$,.0f"
  comparison:
    field: revenue_target_q1
    mode: value
    format: "$,.0f"
    label: "Target"
    polarity: neutral
```

No delta computed. The transform formats the comparison field and appends the label. No indicator. Neutral color.

### Example 5: KPI with Custom Spacing

```yaml
sheet: "Revenue"
data: orders
kpi:
  value: revenue
  format: "$,.0f"
  spacing: 8
  comparison:
    field: revenue_prior_month
    mode: delta_percent
    label: "MoM"
    polarity: up_is_good
```

### Example 6: KPI with Filters

```yaml
sheet: "US Revenue"
data: orders
filters:
  - field: country
    operator: eq
    value: "US"
kpi:
  value: revenue
  format: "$,.0f"
  title: "US Revenue"
  comparison:
    field: revenue_prior_month
    mode: delta_percent
    label: "MoM"
    polarity: up_is_good
```

Filters compile to Vega-Lite `transform` entries prepended to the KPI's delta transforms.

---

## 7. Dashboard Composition

KPI cards compose naturally in the Layout DSL:

```yaml
dashboard: "Sales Overview"
canvas:
  width: 1440
  height: 900

components:
  kpi_revenue:
    type: sheet
    link: "charts/kpi_revenue.yaml"
  kpi_orders:
    type: sheet
    link: "charts/kpi_orders.yaml"
  kpi_arpu:
    type: sheet
    link: "charts/kpi_arpu.yaml"
  kpi_churn:
    type: sheet
    link: "charts/kpi_churn.yaml"

root:
  type: root
  orientation: vertical
  contains:
    - kpi_row:
        type: container
        orientation: horizontal
        height: 120
        padding: "0 16"
        contains:
          - kpi_revenue
          - kpi_orders
          - kpi_arpu
          - kpi_churn
```

Each KPI is a standard `type: sheet` reference. Card backgrounds, borders, and corner radii are applied by the Layout DSL's container styling, not by the Vega-Lite spec.

---

## 8. Pattern Catalog Update

| Pattern | DSL Trigger | Vega-Lite Structure |
|---|---|---|
| KPI / Big number | `kpi` property present | `vconcat` of 2–3 `text` mark sub-specs with `height: 1`, conditional color encoding, `calculate` transforms for delta/indicator |

---

## 9. Edge Cases

| Edge Case | Input Condition | Expected Behavior |
|---|---|---|
| No comparison block | `kpi.comparison` omitted | 2-row vconcat: title + value only. No transforms. |
| Comparison field null in data | Query returns `null` for `comparison.field` | Delta transform produces `null`. Comparison row renders nothing. |
| Value field null in data | Query returns `null` for `kpi.value` | Value row renders nothing. |
| Zero comparison value | `comparison.field` = 0, mode = `delta_percent` | Delta transform produces `null`. Comparison row hidden. |
| Multiple data rows | Query returns >1 rows | Text marks display first datum. |
| Zero data rows | Query returns 0 rows | All text marks render nothing. |
| Delta is exactly zero | `delta = 0` | Shows "▲ 0.0%". Green for `up_is_good` (condition `>= 0` is true). |
| `kpi` with `cols`/`rows`/`marks` | Both present | Warning emitted. `kpi` takes priority. |
| `comparison.field` == `kpi.value` | Same field | Validation error. |
| `spacing: 0` | Explicit zero | Valid. Ultra-compact rendering. |

---

## 10. Files Changed

| File | Action | Description |
|------|--------|-------------|
| `src/schema/chart_schema.py` | modify | Replace `KPIConfig`/`KPIComparison` with `KPIBlock`/`KPIComparison`. New fields: `value`, `format`, `title`, `spacing`, `polarity`, `mode`. Add `kpi_excludes_shelf_properties` validator. |
| `src/translator/translate.py` | modify | Add KPI pattern detection before stacked/single routing. |
| `src/translator/patterns/kpi.py` | create | New pattern compiler: `compile_kpi()` → Vega-Lite vconcat. |
| `src/theme/default_theme.json` | modify | Add `kpi` section with typography, semantic colors, spacing. |
| `src/data/cube_client.py` | modify | Update `_collect_chart_fields()` to extract from new `KPIBlock` fields. |
| `tests/fixtures/yaml/kpi_*.yaml` | create | KPI fixtures for all variants. |
| `tests/test_kpi.py` | create | Full KPI test suite. |
| `docs/guide/dsl-reference.md` | modify | Replace "Not yet supported" KPI section with full docs. |

---

## 11. Future Features

**Parameters (deferred):** KPI comparison switching handled at the semantic layer. KPI block stays static.

**Sparklines (deferred):** Backward-compatible addition as an extra row in the vconcat.

**Interactive KPI selection (deferred):** Depends on cross-chart actions in the Layout DSL.

---

## 12. Out of Scope

- **Time intelligence computation.** Semantic layer's responsibility.
- **Multiple simultaneous comparisons.** One comparison per card.
- **Sparklines.** Deferred.
- **Progress bars / gauges.** Deferred.
- **Conditional formatting rules.** Only polarity-based coloring.
- **KPI-specific layout.** Container styling is a Layout DSL concern.
