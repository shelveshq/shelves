# Review instructions for Shelves

These instructions apply to any code review of this repository (including the
built-in `/code-review`). CLAUDE.md and the module-level CLAUDE.md files hold
general conventions; this file sets review priorities.

## What "Important" means in this repo

Reserve high severity for the bug classes that have actually bitten this
codebase — they outrank generic correctness nits:

1. **Surface drift** — a behavior change applied to one wrapper of
   `compile_chart` / `resolve_model_data` but not the others (render CLI,
   dev CLI, Studio chart route, Studio dashboard route, and the Studio
   watcher callbacks in `lifespan.py`). See `.claude/skills/surface-parity/`.
2. **Backend divergence** — the same chart YAML meaning different things on
   inline data vs DuckDB vs Cube.dev (filters, temporal grains, formats,
   field sets). See `.claude/skills/adapter-parity/`.
3. **DSL propagation gaps** — a new/changed schema property that parses fine
   but never reaches field collection, the translator, Studio validation,
   docs, or the version stamp. See `.claude/skills/dsl-change/`.
4. **Silent failure swallowing** — new `except Exception: pass`,
   `contextlib.suppress(Exception)`, or errors demoted to `warnings.warn`
   (which Studio users never see). Failures must raise typed errors or land
   in the returned `warnings` list with the sheet/file named.
5. **Browser-only breakage** — changes to `shelves/render/` JS assets,
   layout translator output, or sizing that Python tests cannot observe.
   If the diff touches these and was not verified against rendered HTML,
   flag that as a finding in itself. See `.claude/skills/verify-render/`.

## Repo-specific checks

- Path-like parameters (`models_dir`, `data_base_dir`, `theme_path`,
  `charts_dir`) must be resolved at call time and threaded identically to
  both `compile_chart` and `resolve_model_data` at each call site.
- Until the dashboard loops are unified, chart-loop changes must land in
  BOTH `compose_dashboard._compile_chart` and `run_dashboard_pipeline`,
  with tests on both.
- Long-running-server semantics: anything cached (models, theme, JS assets)
  must be read-fresh or invalidated on file change — correct in one-shot CLI
  runs is not evidence for Studio.
- Padding/layout: padding belongs in shared style rules, not on sheets;
  solver-sized containers must not use `display: flex`; fit modes apply to
  rendered sheets, not just schema.
- Typing: prefer `isinstance` narrowing over `getattr`/`cast()`, and
  `Literal` annotations over `cast()`.
- New tests must assert the actual output format (vegaEmbed wrapper,
  StyleProperties) — flag assertions written from memory of the format.

## Do not report

- Anything ruff (lint or format) already enforces.
- Missing validation that would restrict user theme customization — themes
  are deliberately unvalidated; do NOT suggest adding coherence checks.
- Style-only rewrites of untouched code.

## Volume

Cap nits at 5 per review; if there are more, summarize as "plus N similar".
Never pad a review — "no findings" is an acceptable outcome.
