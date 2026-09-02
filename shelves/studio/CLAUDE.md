# Studio — CLAUDE.md

Shelves Studio is the local FastAPI dev-server editor: a browser workspace with a
Monaco YAML editor, a live chart/dashboard preview, a file tree, and an embedded
terminal. It reuses the shared `compile_chart` pipeline — Studio is a **surface**,
not a second compiler. Launch with `python -m shelves.studio.cli` (see root
`CLAUDE.md` for flags).

## Backend (Python / FastAPI)

- `cli.py` — `shelves-studio` entry point. Arg parsing, port preflight
  (`_port_in_use`), banner, browser auto-open, and `--reload` app-factory plumbing
  (config travels via `SHELVES_STUDIO_*` env vars because the reloader re-imports
  the app in a subprocess). Binds `127.0.0.1` literally (not `localhost`) so the
  advertised URL always matches the bind host.
- `server.py` — `create_app(project_dir, theme_path, models_dir, charts_dir,
  dashboards_dir, assets_dir)`. Registers routes, stores config on `app.state`,
  mounts `/static` and `/assets` (the latter via `_LenientStaticFiles`, which
  tolerates a missing dir so users can add `assets/` later without a restart),
  and injects a per-app `terminal_token` `<meta>` into the served HTML.
  Every HTTP endpoint and mount validates the Host header against loopback
  hosts (TrustedHostMiddleware, SHE-52) to block DNS rebinding; `PUT /file`
  enforces the `.yaml/.yml/.json` write allow-list (theme file exempt).
  Tests must use `tests/conftest.py::LoopbackTestClient` — a stock
  TestClient sends `Host: testserver` and gets 400.
- `routes/`
  - `compile.py` — `POST /compile` (YAML → `{vega_lite_spec, errors, warnings,
    model}`) and `GET /schema` (ChartSpec JSON Schema for Monaco).
    `model` is the chart's model name (`spec.data`) on success, `null` on error
    payloads — kept in shape-parity with the watcher broadcast (`lifespan.py`).
    `warnings` are structured objects (`{loc, display_loc, msg, code, source,
    line, col}`, positioned like errors, SHE-101) mirroring the SHE-54
    `ValidationErrorItem` vocabulary — a warning carries a `loc` when its emitter
    (`PositionedWarning`) knows the field (`tooltip[i]`, `kpi`), else `line/col`
    are null (top-of-file fallback). `_format_warnings` resolves locs through the
    shared `resolve_locs` (one parse, **key position** like errors, cleaned
    `display_loc`) — the watcher broadcast (`lifespan.py`) reuses it, so the same
    chart yields identical inline markers whether typed or saved. Both routes
    import these formatters from `routes/_diagnostics` (one implementation).
  - `_diagnostics.py` — the shared diagnostics formatters (SHE-105):
    `_format_yaml_error`, `_format_validation_errors`, `_format_warnings`, plus
    `format_validation_items` (adapts a SHE-54 `ValidationErrorItem` → the Studio
    error shape). `compile.py` and `dashboard.py` both import from here, so the
    two routes paint identical inline markers. (`compile.py` re-exports the three
    `_format_*` names for `lifespan.py` and the chart-route tests.)
  - `dashboard.py` — `POST /compile-dashboard` (dashboard YAML → `{html, canvas,
    component_tree, errors, warnings}`). Errors and warnings are **positioned
    structured objects** at parity with the chart route (SHE-105): schema +
    YAML-syntax errors come from the SHE-54 renderer (`validate_dashboard_yaml`,
    the same one MCP `validate_spec` uses, called BEFORE the compile pipeline);
    sheet-level warnings anchor on the sheet node in the dashboard YAML (a
    `sheet-name → dashboard-loc` map correlated by link — **only links that
    occur exactly once** are anchored; a duplicated link stays top-of-file rather
    than risk a wrong node, since raw-document and flatten-discovery order need
    not agree); filter-domain warnings
    anchor on the `filter:` node (a `(model, field) → dashboard-loc` map,
    `_build_filter_loc_map`). Parameter-domain warnings (from
    `load_parameter_set`, tied to the parameter declaration in `parameters.yaml`,
    not the layout `parameter:` control), legend, and deep runtime
    errors/warnings degrade to top-of-file (null line/col) when no clean loc is
    expressible — never a misleading anchor. A **missing/traversal sheet stays a warning** (the
    dashboard still renders): `validate_dashboard_yaml` is called with
    `project_dir=None` so it does not promote a missing sheet to an error.
  - `files.py` — `GET /project` (directory tree), `GET/PUT/POST/DELETE /file`,
    `POST /file/rename`. `resolve_safe` rejects path traversal on every
    endpoint; create/rename/delete are restricted to `.yaml/.yml/.json` and
    broadcast `file_change` directly (the watcher's own event may duplicate
    it; the sidebar debounces). New files get a starter template chosen by
    the configured dir they land in (`template_for`). `GET /project` returns
    typed top-level groups (charts/dashboards/models/assets) built from the
    configured dirs; the three primary groups are listed even when empty or
    missing so the UI can offer "create first file" (assets stays
    omit-when-empty); paths stay relative to `project_dir`.
    When `--theme` is set, the tree gains a top-level theme entry — real
    relative path when the theme is inside the project, else the exact-match
    alias `@theme/<name>` that only GET/PUT `/file` resolve (never
    create/rename/delete). Theme writes broadcast `theme_changed` so clients
    recompile.
  - `terminal.py` — PTY-backed terminal over `WS /ws/terminal`, token-gated.
- `lifespan.py` — startup/shutdown; wires the file watcher and pushes results
  over the broadcast WebSocket. The watcher callback is the module-level
  `handle_fs_event` (testable); theme-file events broadcast `theme_changed`
  instead of attempting a compile. The theme path is in the watch scope, but
  a theme OUTSIDE project_dir is not watched (the watch roots at
  project_dir) — Studio saves to it still recompile via PUT /file's direct
  broadcast; external edits to it don't live-reload (known limitation).
- `watcher.py` — filesystem watch → recompile → broadcast `file_change` /
  `compile_result` to connected clients.
- `connection.py` — `ConnectionManager` (broadcast WS fan-out for live reload).
- `yaml_position.py` — maps compile errors back to YAML line/col for Monaco markers.

## Frontend (`static/`, vanilla ES modules — no build step)

- `index.html` — the shell: header, `#workspace` grid (sidebar | editor |
  resize-handle | preview), terminal panel, status bar. Loads Vega/Vega-Lite/
  vega-embed from `static/vendor/` (same-origin, see below) and Monaco from CDN.
- `vendor/` — committed pinned UMD builds of vega, vega-lite, vega-embed
  (SHE-77). Served at `/static/vendor/`; the dashboard preview iframe loads the
  same copies via `translate_dashboard(vega_src_base="/static/vendor")`. The
  canonical file list is `VEGA_LIB_FILES` in `shelves/render/to_html.py` —
  upgrading a version means re-downloading the file AND updating that constant
  (standalone CLI HTML uses the matching pinned CDN URLs). Also holds the
  monaco-yaml worker bundle (`monaco-yaml-worker-*.min.js`, SHE-48): built
  from monaco-yaml's `yaml.worker.js` against the SAME monaco-editor version
  editor.js's loader pins (rebuild command in the file's banner) — a
  version-mismatched worker kills all YAML diagnostics silently.
- `styles.css` — all styling. Has its **own** `:root` design tokens that predate
  and **diverge from** the Shelves design system (see `docs/design-system/`).
- `js/` (each module subscribes to DOM `CustomEvent`s — no cross-module imports of
  state beyond `state.js`):
  - `main.js` — bootstraps modules; the compile router that dispatches YAML to the
    chart vs dashboard path (`isDashboardYaml`). Boot is **parallel** (SHE-64):
    tree/preview/WS start immediately and must never be awaited behind Monaco;
    `initEditor` self-guards (error card in `#editor-boot` on failure/timeout)
    and `openFile` awaits its `editorReady` promise.
  - `state.js` — shared `state` object, constants, status-bar + breadcrumb render.
  - `editor.js` — Monaco setup, debounced compile (`POST /compile`), Cmd+S save,
    compile-marker application, and the **pointer-captured editor/preview pane
    resize handle**;
    error AND warning markers are positioned by `line`/`col` when the item is a
    structured object (both routes now emit objects, SHE-101/SHE-105), and fall
    back to a top-of-file span for a locless object or a stray string; error/
    warning squiggle colors come from the DS
    `--danger`/`--warning` tokens in the `shelves` Monaco theme (SHE-101).
    `fixedOverflowWidgets: true` renders hover/suggest widgets in a body-level
    container so a long marker hover isn't clipped by a narrow editor pane
    (width capped via `.monaco-hover` in `styles.css`);
    ChartSpec schema is attached to monaco-yaml only while the open buffer
    classifies as chart YAML (`shelves:buffer-kind` event from main.js's router).
    Saves are confirmed: dirty clears only on a 2xx PUT; failures surface as a
    persistent status-bar error (150ms-gated "Saving…" / 2s "Saved" otherwise).
    Dirty buffers are guarded (beforeunload + confirm-on-switch); a
    deleted-on-disk open file shows a status/breadcrumb notice and is never
    auto-closed.
  - `preview.js` — chart render via `vegaEmbed` (with the shared label patch),
    Data view (SHE-43: resolved-rows table from `vega_lite_spec.data.values` —
    model-name header, 500-row cap, skipped/empty states; replaced the old
    JSON view), error overlay, `ResizeObserver` re-fit. The re-fit
    (`refitChart`, SHE-100) re-measures the container and sets the view's
    width/height before `resize()` — a bare `view.resize()` does NOT re-fit a
    `container`-sized/`autosize:fit` spec, so the chart would keep its old size
    and clip; compound (scroll) specs are left at natural size.
  - `dashboard.js` — dashboard compile + iframe preview, canvas scaling / zoom.
  - `sidebar.js` — file tree fetch/render, collapse state, sidebar show/hide,
    and file management (SHE-42): group-header `+`, right-click context menu
    (New / Rename / Duplicate / two-step Delete), inline create/rename inputs.
    The menu reuses the `.sh-menu` DS atoms (SHE-36). Renaming the open file
    updates `state.currentFile.path` in place — the buffer (dirty or not) is
    never dropped.
  - `nav.js` — back/forward file-navigation history (SHE-40): stack in
    `state.nav`, topbar chevrons, `Cmd/Ctrl+[`/`]` (shadowing Monaco's
    outdent/indent — Tab/Shift+Tab still indent) + mouse buttons 3/4. All
    navigation funnels through `openFile` (injected via `initNav`), so the
    dirty-buffer confirm applies; files deleted since being opened are
    pruned and navigation falls through to the next entry. `openFile` probes
    `GET /file` BEFORE the dirty confirm (a missing target must not consume a
    "discard" answer — the prune walk prompts at most once) and only a
    definite 404 maps to `'not-found'`/pruning; any other failure is
    `'error'`, which keeps the history entry.
  - `terminal.js` — xterm.js terminal tabs over the terminal WS.
  - `websocket.js` — single broadcast WS (`/ws`) → typed DOM events
    (`compile_result`, `file_change`, `dashboard_compile_result`,
    `theme_changed`).

## Event flow

`editor.js` debounces `onDidChangeModelContent` → `main.js` compile router →
`POST /compile[-dashboard]` → dispatches `shelves:compile-result` /
`shelves:dashboard-result` → `preview.js`/`dashboard.js` render + `editor.js`
paints Monaco markers + `state.js` updates the status bar. The watcher pushes the
same events for external file edits over `/ws`.

## Conventions

- **No build step.** Plain ES modules; render libs and the monaco-yaml worker
  are vendored static bundles (`static/vendor/`, SHE-77/SHE-48 — same-origin
  beats CDN-at-runtime), the Monaco editor itself still loads from a
  version-pinned CDN. Keep it that way unless a ticket says otherwise.
- Modules communicate via `document` `CustomEvent`s, not direct calls, so a new
  surface can subscribe without touching existing modules.
- Compile requests are sequence-guarded (`compileSeq`) so a slow response can't
  overwrite a newer one — preserve this when touching compile paths.
- Path safety: every file read/write goes through `resolve_safe`. Never bypass it.
- Security posture (SHE-52): HTTP = loopback Host allow-list + write
  extension allow-list; terminal WS = loopback Origin + per-app token. New
  endpoints must not weaken either; new write paths go through
  `_ALLOWED_WRITE_EXTENSIONS`.

## Design system

The authoritative Studio design lives in `docs/design-system/studio/` (mirror of the
Claude Design project "Shelves Studio", built on the "Shelves Design System"). Two
files carry the truth:
- `studio/tokens.css` — a **bridge** that remaps Studio's *existing* var names
  (`--bg-primary`, `--text-*`, `--accent`, `--term-*`, `--font-ui`, …) — the same
  ones in `static/styles.css` — onto the design-system tokens. `--font-ui →
  --font-mono` flips the whole UI to mono in one line.
- `studio/studio.css` — the real component stylesheet (`.sh-*` classes), portable
  wholesale.

`static/styles.css` consumes the DS tokens via two served copies —
`static/shelves-tokens.css` (mirror of `docs/design-system/colors_and_type.css`)
and `static/tokens-bridge.css` (mirror of `docs/design-system/studio/tokens.css`),
loaded in that order before `styles.css`. Re-sync = re-copy those two files.
`styles.css`'s own `:root` holds only layout state (`--sidebar-width`,
`--editor-width`) and `--radius-*` compat aliases. Component-level fidelity to
`studio.css` is tracked per-ticket (SHE-34/35/36/47). The real Studio layout is **3 columns + a 1px splitter**
(tree | editor | splitter | preview), and the inspector is a **preview mode**
(view modes: chart / dashboard / model / theme / empty), not a permanent column.
The repo Studio's chart preview now has modes chart / data (SHE-43 replaced the
JSON view with the Data table); the design's `model` and `theme` inspector modes
are not yet implemented.
Multi-tab, command palette, and a recents empty state are designed but deferred.
See `docs/design-system/studio/README.md` for the full adherence analysis.

## Known gaps (as of 2026-07 studio UX epic)

- **Multi-tab editor** from the design (`editor.html`) is not implemented — Studio
  is single-file.
