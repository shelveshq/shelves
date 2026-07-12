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
- `routes/`
  - `compile.py` — `POST /compile` (YAML → `{vega_lite_spec, errors, warnings}`)
    and `GET /schema` (ChartSpec JSON Schema for Monaco).
  - `dashboard.py` — `POST /compile-dashboard` (dashboard YAML → `{html, canvas,
    component_tree, errors, warnings}`).
  - `files.py` — `GET /project` (directory tree), `GET/PUT /file`. `resolve_safe`
    rejects path traversal; `build_tree` walks the tree filtering to
    `.yaml/.yml/.json` + dirs. `GET /project` returns typed top-level groups
    (charts/dashboards/models/assets) built from the configured dirs; paths stay
    relative to `project_dir`.
  - `terminal.py` — PTY-backed terminal over `WS /ws/terminal`, token-gated.
- `lifespan.py` — startup/shutdown; wires the file watcher and pushes results
  over the broadcast WebSocket.
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
    compile-marker application, and the **editor/preview pane resize handle**;
    ChartSpec schema is attached to monaco-yaml only while the open buffer
    classifies as chart YAML (`shelves:buffer-kind` event from main.js's router).
    Saves are confirmed: dirty clears only on a 2xx PUT; failures surface as a
    persistent status-bar error (150ms-gated "Saving…" / 2s "Saved" otherwise).
    Dirty buffers are guarded (beforeunload + confirm-on-switch); a
    deleted-on-disk open file shows a status/breadcrumb notice and is never
    auto-closed.
  - `preview.js` — chart render via `vegaEmbed` (with the shared label patch),
    JSON view, error overlay, `ResizeObserver` re-fit.
  - `dashboard.js` — dashboard compile + iframe preview, canvas scaling / zoom.
  - `sidebar.js` — file tree fetch/render, collapse state, sidebar show/hide.
  - `terminal.js` — xterm.js terminal tabs over the terminal WS.
  - `websocket.js` — single broadcast WS (`/ws`) → typed DOM events.

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
Multi-tab, command palette, and a recents empty state are designed but deferred.
See `docs/design-system/studio/README.md` for the full adherence analysis.

## Known gaps (as of 2026-07 studio UX epic)

- **Pane resize is crude** — global `mousemove` listeners, no pointer capture, no
  iframe-overlay during drag (dashboard iframe swallows mouse events mid-drag).
- **No editor/preview history** — no back/forward between opened files.
- **Sidebar can't be reopened** once collapsed from inside the sidebar (the only
  toggle lives *in* the sidebar header).
- **No file creation** from the UI (create/rename/delete); `PUT /file` can create,
  but nothing drives it.
- **Multi-tab editor** from the design (`editor.html`) is not implemented — Studio
  is single-file.
