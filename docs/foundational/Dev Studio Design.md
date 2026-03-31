# Charter Studio: Interface Design Document

This document captures the design rationale, architecture, and implementation plan for Charter Studio — the analyst-facing authoring environment for the Charter platform.

---

## 1. Problem Statement

Charter needs an interface that connects three things with minimal friction: a YAML authoring surface, a deterministic translation pipeline, and a rendering layer. The question is what form that interface should take.

Three options were evaluated: a full React/Next.js web application, a VS Code extension, and a purpose-built local dev server that can optionally be wrapped in a native macOS app. The third option was selected.

---

## 2. Options Evaluated

### 2.1 Full Web Application (React / Next.js)

This is the current Phase 6 plan (KAN-103). It's the ultimate north star for business users, but it presents significant challenges as the first interface:

- Massive frontend engineering effort — state management, routing, auth, responsive design, dashboard navigation, filter propagation.
- Requires deep JS/TS knowledge, which is outside the project's core skillset.
- Building it before the core pipeline is rock-solid means fighting two battles at once.
- Doesn't play to Charter's code-first, version-controlled identity.

**Verdict:** Keep as the long-term goal for business users. Not the right first interface for analysts.

### 2.2 VS Code Extension

Closer to the right idea — meet the analyst where they already live — but has real limitations:

1. The extension API is TypeScript-only. The webview panel is sandboxed with awkward message-passing between the host process and the webview, complicating real-time preview.
2. Content Security Policy restrictions in webview panels make embedding Vega-Lite and VegaFusion painful.
3. Maintaining a VS Code-specific packaging and publishing workflow has nothing to do with the core product.

The key insight is that Monaco Editor (which powers VS Code's editing experience) is available as a standalone JS library via CDN. You get the exact same editing UX without any of the extension overhead.

**Verdict:** Rejected. Monaco gives us VS Code's editor without VS Code's framework.

### 2.3 VS Code Fork

A fork gives total control but saddles the project with maintaining a massive Electron codebase — tracking upstream updates, handling Electron security patches, managing OS-specific builds. That's a full-time job for a team, not a solo project. The fork approach only makes sense for developer tool companies (Cursor, Zed, etc.). Charter is a BI platform.

**Verdict:** Rejected. Maintenance burden is unjustifiable.

### 2.4 Charter Studio: Local Dev Server + Native App (Selected)

A lightweight local dev server with a split-pane HTML interface. Think of it like Storybook, Jupyter, or Vite's dev server: run a command, a browser tab opens, and you get a purpose-built environment.

- Left pane: Monaco editor with YAML syntax highlighting and Charter schema validation.
- Right pane: Vega-Lite render output, hot-reloading on every keystroke.
- Bottom panel: Integrated terminal (xterm.js + PTY) for running CLI agents (Claude Code, Codex, Aider, or any shell command).
- Sidebar: File explorer showing project structure.

This approach gives everything needed:

- Zero dependency on VS Code's extension API or codebase.
- Monaco editor provides the same editing experience as VS Code (autocomplete, error squiggles, minimap).
- Hot-reload preview uses the existing `to_html.py` render pipeline.
- The terminal is a real PTY-backed shell — tool-agnostic, works with any CLI agent.
- Ships as `pip install charter[studio]` → `charter dev` → browser opens. One command.
- The entire thing is Python-served, matching the existing stack.
- Version control is native — editing files on disk, git works normally.

**Verdict:** Selected. Lowest build effort, best fit for the code-first workflow, smooth upgrade path.

---

## 3. Architecture

```
charter dev
    → FastAPI server on localhost:5173
    → Serves single HTML page with:
        - Monaco editor (YAML + Charter schema validation)
        - Vega-Lite live preview pane (hot-reload on keystroke)
        - Integrated terminal (xterm.js + PTY — run Claude Code, Codex, Aider, or any CLI)
        - File explorer sidebar
        - Dashboard composition view (Layout DSL)
    → WebSocket for file watch + hot-reload
    → Existing pipeline: YAML → Pydantic → Vega-Lite → theme → render
```

### 3.1 Server Layer

A FastAPI application with the following endpoints:

- **Static serving** — serves the single-page HTML workspace.
- **WebSocket `/ws`** — pushes re-render messages on file changes.
- **File watcher** — uses `watchfiles` to monitor `.yaml` files. On change: re-runs the pipeline, sends compiled Vega-Lite JSON over the WebSocket.
- **`POST /compile`** — accepts YAML content, runs the pipeline, returns `{vega_lite_spec, errors, warnings}`.
- **`GET /project`** — returns directory tree for the file explorer.
- **`GET/PUT /file`** — reads/writes file content on disk.
- **WebSocket `/ws/terminal`** — bridges a PTY subprocess to the browser terminal.

### 3.2 Frontend Layer

A single HTML page with no build step. All libraries load from CDN:

- **Monaco Editor** via `@monaco-editor/loader` — YAML editing with Charter JSON Schema validation (generated from Pydantic `ChartSpec.model_json_schema()`).
- **Vega-Lite + vega-embed** — renders compiled specs in the preview pane.
- **xterm.js + xterm-addon-fit** — renders the integrated terminal with full ANSI color support.

### 3.3 AI Integration

The terminal panel is a real PTY-backed shell, not a custom chat UI. The analyst runs whatever CLI agent they prefer — Claude Code, Codex, Aider, or plain shell commands. The integration is simple:

```
Analyst types in terminal:  claude "add a dual axis overlay of ARPU as dashed line"
    → Agent reads charts/revenue.yaml from disk
    → Agent writes modified charts/revenue.yaml to disk
    → File watcher detects change
    → WebSocket pushes re-compiled Vega-Lite spec
    → Preview pane re-renders
    → Monaco editor reloads file content (if the same file is open)
```

This approach is tool-agnostic, requires zero API integration, and inherits the user's full environment (API keys, PATH, virtualenvs).

---

## 4. Two Views

### 4.1 Editor View (Chart YAML)

For individual chart authoring. Split pane with Monaco editor on the left, Vega-Lite preview on the right. The preview has three sub-modes: rendered chart (vegaEmbed), raw Vega-Lite JSON, and dashboard canvas.

### 4.2 Dashboard View (Layout DSL)

For dashboard composition. Editor pane narrows (~220px) to give the canvas preview more space. The preview renders the full Layout DSL output — a scaled-down version of the 1440×900 canvas showing all nested containers, sheet components, text blocks, and navigation elements. Clicking a sheet in the preview opens the linked chart YAML in the editor. A component tree strip below the preview shows the flattened structure: `root → container (h) → kpi_rev · kpi_orders · container (v) → ...`

---

## 5. Staged Evolution

### Stage 1: CLI + Browser Tab

`pip install charter[studio]` → `charter dev` → browser opens.

FastAPI serves the workspace HTML. File watcher triggers WebSocket push on YAML change. Preview pane re-renders via vegaEmbed. This is the working tool while the core pipeline matures.

Build effort: days, not weeks. The entire translation pipeline already exists.

### Stage 2: Tauri Native App

Wrap the same HTML in a Tauri v2 shell. Produces a native `.app` / `.dmg` with dock icon, Cmd+S, native menu bar. Uses macOS WebKit (not Chromium) — ~5MB bundle vs Electron's 150MB+. The Python FastAPI server runs as a Tauri sidecar process.

Zero frontend code changes from Stage 1. The web content is identical — just swapping the browser chrome for native chrome.

This is the Figma desktop app model: a native wrapper around a web application, with OS-level integrations that justify being an app rather than a browser tab.

### Stage 3: Native OS Integrations

File associations (`.yaml` opens in Charter Studio), "Open Recent" menu, OS notifications for long operations, auto-update, `Cmd+,` preferences panel, drag-and-drop.

### Key Constraint: 100% Shared Frontend

The same HTML/CSS/JS runs at every stage. Monaco editor, preview pane, terminal, file explorer — all identical whether in a browser tab or a Tauri native window.

---

## 6. Key Design Decisions

### Monaco via CDN, not VS Code fork

Standalone `@monaco-editor/loader` gives full editor UX (autocomplete, error squiggles, minimap, syntax highlighting) without maintaining a VS Code codebase. The Charter JSON Schema (generated from Pydantic models) provides domain-specific autocomplete and validation.

### Tauri over Electron

Tauri uses the OS native WebView (WebKit on macOS, WebView2 on Windows). The app bundle is ~5MB vs Electron's 150MB+. The Rust shell is a thin scaffold that spawns the Python sidecar via IPC — no Rust coding required beyond configuration.

### Real terminal, not custom AI chat

A PTY-backed xterm.js terminal rather than a custom Anthropic API integration. This is tool-agnostic (Claude Code, Codex, Aider, any CLI), requires zero API integration code, and inherits the user's full environment. The file watcher is the integration layer — agents edit files on disk, the watcher detects changes, the preview reloads.

### Single HTML page

The entire frontend is one page with split panes. No React, no build step, no `node_modules`. Libraries load from CDN. This keeps the project firmly in the Python ecosystem and avoids introducing a JS/TS build toolchain.

### Two views, one workspace

Editor view for chart YAML authoring; Dashboard view for Layout DSL composition. Toggle via toolbar. Both use the same Monaco editor and the same preview infrastructure — the only difference is what the preview renders (a single Vega-Lite chart vs a full dashboard canvas).

---

## 7. Relationship to Other Components

### Dependencies

- **KAN-95** (Phase 1 core pipeline) — need chart rendering for preview.
- **KAN-99** (Phase 2 theme) — need theme merge for preview.
- **KAN-101** (Phase 4 Layout DSL) — needed for the dashboard composition view.

### Replaces Phase 6 Scope Partially

KAN-103 (Web Application) becomes the business-user-facing hosted version. Charter Studio is the analyst-facing local tool. They share the same underlying pipeline. When the full web app ships, Charter Studio becomes its "developer mode" — same Monaco editor, same preview, just hosted rather than local.

### Upgrade Path

The web app (Phase 6) and Charter Studio coexist as two entry points for different user types:

- **BI Analysts** use Charter Studio locally. They write YAML, use CLI agents, version-control with git.
- **Business Users** use the hosted web app. They write natural language prompts, the LLM generates YAML, the same pipeline renders the charts.

Both converge on the same intermediate representation (the YAML DSL) and the same deterministic translation pipeline. This is the "two entry points, one pipeline" architecture described in the Vision document.

---

## 8. Jira Epic and Stories

**Epic:** KAN-204 — Charter Studio — Local Dev Server + Native App

| Ticket | Summary | Stage |
|--------|---------|-------|
| KAN-205 | FastAPI dev server with file watcher and WebSocket hot-reload | Stage 1 |
| KAN-206 | Monaco editor integration with Charter YAML schema validation | Stage 1 |
| KAN-207 | Live Vega-Lite preview pane with theme-applied rendering | Stage 1 |
| KAN-208 | File explorer sidebar and project structure navigation | Stage 1 |
| KAN-209 | Dashboard composition view for Layout DSL editing | Stage 1 |
| KAN-210 | Integrated terminal panel — xterm.js with PTY for CLI agents | Stage 1 |
| KAN-211 | CLI entry point — charter dev command via pyproject.toml | Stage 1 |
| KAN-212 | Tauri shell — wrap web UI in native macOS app with sidecar | Stage 2 |
| KAN-213 | Native OS integrations — file associations, recent projects, menus | Stage 3 |

### Execution Sequence

Stage 1 critical path:

```
KAN-211 (CLI entry point)
    ↓
KAN-205 (FastAPI server + file watcher)
    ↓
KAN-206 + KAN-207 (Monaco editor + preview pane — parallel)
    ↓
KAN-208 (file explorer)
    ↓
KAN-210 (integrated terminal)
    ↓
KAN-209 (dashboard composition view — depends on KAN-101)
```

---

## 9. Out of Scope

- Full React/Next.js web application (remains KAN-103, Phase 6).
- Multi-user / hosted deployment.
- Authentication / authorization.
- Custom AI chat UI or direct Anthropic API integration (the terminal handles this).
- Business-user natural language prompt UI (deferred to web app).
- Filter interactivity / cross-chart actions (requires JS runtime from KAN-124/125).
