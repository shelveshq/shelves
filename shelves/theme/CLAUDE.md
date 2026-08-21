# Theme — CLAUDE.md

## Files

- `default_theme.yaml` — Built-in two-section theme (chart + layout). Users copy and customize it.
- `theme_schema.py` — `ThemeSpec` Pydantic model with `ChartTheme` (VL config, extra="allow") and `LayoutTheme` (structured tokens).
- `merge.py` — `load_theme()` reads YAML + resolves preset colors, `merge_theme()` merges chart section into VL spec.

## Key Rules

- **Preset color resolution:** `layout.presets.*.color` supports `"text.primary"` / `"text.secondary"` / `"text.tertiary"` references, resolved at load time by `_resolve_preset_colors()`. Unknown references raise `ValueError`.
- **ChartTheme is permissive:** `extra="allow"` lets any Vega-Lite config key through. Don't add explicit fields unless you need validation on them.
- **Layout section never leaks into VL config.** `merge_theme()` extracts only `theme.chart` for the Vega-Lite spec. Layout tokens are consumed by the Layout DSL renderer (`shelves/translator/layout*.py`).
- **`ControlTokens` / `FilterTokens` `text` (SHE-84):** widget/label text color, default `#1a1a1a` (matches `layout.text.primary`), emitted as `--shelves-control-text` / `--shelves-filter-text`. Needed so filter/parameter widgets stay legible on a dark control/filter surface.
- **`LegendTokens` (SHE-85):** independent-dashboard-legend styling, emitted as `--shelves-legend-*` custom properties by `layout.py` on any dashboard that has legends. `legend_render.js` reads each as `var(--shelves-legend-*, <default>)`, so defaults (which match the pre-token hardcoded values exactly) render standalone. Unvalidated, like every other layout token.
- `kpi_tokens.py` — resolves KPI-specific theme tokens (used by KPI sheets).
