# Theme — CLAUDE.md

## Files

- `default_theme.yaml` — Built-in two-section theme (chart + layout). Users copy and customize it.
- `theme_schema.py` — `ThemeSpec` Pydantic model with `ChartTheme` (VL config, extra="allow") and `LayoutTheme` (structured tokens).
- `merge.py` — `load_theme()` reads YAML + resolves preset colors, `merge_theme()` merges chart section into VL spec.

## Key Rules

- **Preset color resolution:** `layout.presets.*.color` supports `"text.primary"` / `"text.secondary"` / `"text.tertiary"` references, resolved at load time by `_resolve_preset_colors()`. Unknown references raise `ValueError`.
- **ChartTheme is permissive:** `extra="allow"` lets any Vega-Lite config key through. Don't add explicit fields unless you need validation on them.
- **Layout section never leaks into VL config.** `merge_theme()` extracts only `theme.chart` for the Vega-Lite spec. Layout tokens are consumed by the Layout DSL renderer (future).
