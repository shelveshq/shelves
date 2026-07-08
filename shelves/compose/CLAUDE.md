# Compose — CLAUDE.md

This module orchestrates **dashboard composition**: dashboard YAML → per-sheet
chart compilation → legend linking → layout translation → one HTML string.

## Files

- `dashboard.py` — `compose_dashboard()` (the CLI/compose surface),
  `compile_dashboard_charts()` (the shared per-sheet compile loop),
  `link_legends()` (shared legend discovery + resolution), and the flat-tree
  walkers (`_discover_sheets`, `_discover_legends`).
- `legend_link.py` — legend → scale linking and in-sheet legend suppression
  (SHE-10). Pure helpers over compiled VL encodings; no HTML/layout knowledge.

## The one dashboard chart loop

`compile_dashboard_charts()` is the ONLY per-sheet compile loop. Both surfaces
call it — `compose_dashboard` (CLI) and the Studio dashboard route
(`shelves/studio/routes/dashboard.py::run_dashboard_pipeline`). **Never
reintroduce a second loop**; if a surface needs different behavior, extend the
shared function's parameters.

Per-surface presentation is the only difference:

| | compose (CLI) | Studio route |
|---|---|---|
| `fail_fast` | `True` — missing file raises `FileNotFoundError`, compile error raises `RuntimeError` | `False` — both become warnings; the sheet renders as an empty box |
| `restrict_links` | `False` — local dashboards may reference charts outside `--chart-dir` via `../` | `True` — links resolving outside `charts_dir` (absolute or `../`) are skipped with a warning (mirrors `resolve_safe`) |
| returned warnings | re-emitted via `warnings.warn` | returned in the `warnings: [...]` payload |

Warning messages show the link as written in the YAML; only the fail-fast
exceptions include the resolved absolute path (never surfaced to Studio
clients).

Invariants the loop guarantees (do not break):

- **Data-resolution failures are never fatal and never silent** — always a
  `"Data resolution skipped for '<sheet>': ..."` warning; the chart renders
  without data.
- **One `models_dir`/`data_base_dir`** feeds compilation, data resolution, and
  resolver construction — the halves of a compile can't read different model
  directories.
- **SHE-27 lock-step:** the resolver is built before `chart_specs`/`resolvers`
  are published, so legend linking never dereferences a resolver that was
  never built.
- **Python warnings are captured** (via `shelves.diagnostics.capture_warnings`)
  into the returned warnings list, prefixed with the sheet name, so Studio
  users see KPI/tooltip notices too.
