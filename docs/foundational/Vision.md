# Project Vision: Charter — AI-Native Declarative Visual Analytics Platform

## Vision

To build an enterprise-grade, version-controlled visual analytics platform that replaces traditional drag-and-drop BI interfaces (like Tableau) with AI-assisted natural language. Instead of generating raw, error-prone code, the AI acts as a translation layer — converting user prompts into a strict, custom YAML domain-specific language (DSL). This DSL is the core intellectual property of the platform: a Tableau-inspired shelf grammar that any BI analyst can read and write, but that also serves as a tightly constrained output format for LLMs. The YAML configurations seamlessly orchestrate a semantic data layer, a global design system, and a declarative rendering engine to build interactive, composable dashboards — all deterministically, all version-controlled via GitHub.

## Core Insight: The Beneficial Intermediate Representation

The platform's key architectural decision is introducing a custom DSL between natural language and Vega-Lite. Instead of the brittle pipeline `prompt → Vega-Lite` (large output space, high hallucination risk), the system uses:

```
prompt → YAML DSL → Vega-Lite
```

This decomposes one hard translation into two easier ones. The LLM produces compact, constrained YAML. The YAML-to-Vega-Lite translation is deterministic code — no AI, no errors. The DSL is also human-authored by BI analysts, meaning the same intermediate format serves both user types through the same downstream pipeline.

## Two DSLs, One Pipeline

### Chart DSL — What to visualize

A Tableau-inspired shelf grammar for defining individual charts. Analysts who think in terms of rows, columns, marks, color, and detail can write chart specs without learning Vega-Lite.

Key design decisions:
- **`rows`/`cols` are exclusively for axis encoding.** Chart partitioning into small multiples is handled by a separate `facet` property. This is a deliberate improvement over Tableau, where the Rows/Columns shelves conflate axis assignment with view partitioning. In this DSL, the intent is always unambiguous.
- **Per-measure encoding via measure entries.** Each measure on a multi-measure shelf is a `MeasureEntry` object carrying its own `mark`, `color`, `detail`, `size`, and `opacity`. No parallel arrays, no zipping. The mark lives right next to its measure — readable for humans, reliable for LLMs.
- **Layers nest inside measure entries.** A `layer` property on a `MeasureEntry` means "overlay these additional measures in the same chart space." The parent measure is the primary; layers are additions. This makes multi-axis charts composable with stacked panels (the "stacked layers" pattern — the most complex realistic case).
- **Three-level inheritance.** Encoding properties cascade: top-level → measure entry → layer entry. More specific wins. `marks: line` at the top level is a default; `entry.mark: bar` overrides it; `layer.mark: {type: line, style: dashed}` overrides the entry. Same for color, detail, size.
- **At most one multi-measure shelf.** A validator enforces that only one of `rows`/`cols` can be a list of `MeasureEntry` objects. No 2×2 ambiguity.
- **Semantic layer references only.** Fields like `revenue` and `country` are names from the semantic layer menu — never raw SQL, column expressions, or calculated fields.
- **No styling.** The theme layer handles all visual aesthetics. The LLM cannot hallucinate off-brand colors.

### Layout DSL — Where to place it

A dashboard composition grammar based on Tableau's nested container model. Dashboards are trees of horizontal and vertical flex containers holding chart sheets, text blocks, images, navigation elements, and spacers.

Key design decisions:
- **Fixed canvas size** (e.g., 1440×900px) eliminates responsive design complexity in v1.
- **The tree IS the layout.** Containers define their children inline via `contains`. You read the YAML top-to-bottom and see the dashboard structure directly.
- **Three ways to place a child.** A `contains` list accepts string references (to pre-defined components), inline anonymous definitions (quick spacers, labels), and inline named definitions (sheets, sub-containers). Mix freely.
- **Shared styles with inline overrides.** A `styles` dictionary defines reusable presets. Components reference by name and override inline. An `html` property provides a raw CSS escape hatch that supersedes everything.
- **Sheet references link to chart specs** — the layout defines *where* things go, chart YAMLs define *what* each chart looks like, and the theme defines *how* everything is styled. Three independent, version-controllable layers.
- **Deterministic CSS flexbox translation.** Vertical container → `flex-direction: column`, horizontal → `row`. No ambiguity.
- **Static output in v1.** No interactive filters or cross-chart actions. Navigation between dashboards is the only "interactive" element. Filter interactivity is deferred to a future revision.

## Five-Layer Architecture

### 1. Semantic Data Layer (Cube.dev / dbt Semantic Layer / Malloy)

The single source of truth for all business logic. Defines metrics, dimensions, joins, and access controls as code. The LLM picks from a fixed "menu" of available metrics — it cannot hallucinate SQL, invent columns, or miscalculate business logic.

This layer is also the primary performance optimization: all aggregation happens server-side. A chart showing weekly revenue by country across 10 million transactions sends ~500 aggregated rows to the browser, not 10 million.

### 2. Chart DSL Layer

The YAML grammar translating Tableau's shelf model into a structured, machine-readable format. Each YAML file defines one chart. The DSL-to-Vega-Lite translator handles a finite catalog of chart patterns (simple bar, multi-measure stacked panels, layered multi-axis, faceted views, KPIs, scatter plots, etc.), each implemented as a deterministic "recipe."

### 3. Layout DSL Layer

The YAML grammar for dashboard composition. Nested containers, chart references, text blocks, images, navigation elements, and spacers — all translating deterministically to CSS flexbox HTML.

### 4. Theme Layer (Figma → Style Dictionary → Vega-Lite Config)

An automated, deterministic pipeline from design tools to chart styling:

```
Figma Design System
    → Export plugin (W3C Design Tokens Format JSON)
    → Style Dictionary (custom Vega-Lite formatter)
    → theme.json (valid Vega-Lite config object)
    → Merged into every chart at render time
```

The token-to-Vega-Lite mapping is a one-to-one, codified-once function — not AI-driven. For example: `color.primary.500` → `mark.color` and `range.category[0]`; `font.family.body` → `axis.labelFont`; `border.radius.sm` → `bar.cornerRadius`. When a designer updates tokens in Figma, the pipeline regenerates `theme.json` automatically and all dashboards update.

This is a genuine competitive differentiator against Tableau, whose theming is notoriously difficult to maintain (fragile workbook-level formatting, admin-gated server defaults, no design tool integration). Dark mode and multi-brand theming become trivially achievable — just a different token set through the same pipeline.

### 5. Rendering Layer (Vega-Lite + VegaFusion)

Vega-Lite compiles chart specs into interactive Canvas-rendered visualizations. Its comfortable performance range is ~10,000 data points per chart, which is rarely an issue for BI dashboards after semantic layer pre-aggregation.

For remaining transforms (window functions, cross-filter recalculations), VegaFusion partitions computation between a server-side Rust runtime and the browser client. VegaFusion is open-source (BSD-3), battle-tested at Hex (where it powers cross-filtering over 20M+ rows), and is now an official part of the Vega ecosystem.

Canvas rendering is the default (2–10x faster than SVG for redraws). SVG is available as an export option for print-quality output.

## Two User Types, Same Pipeline

**BI Analysts** use Charter Studio — a local dev server with a split-pane interface: Monaco editor on the left, live Vega-Lite preview on the right, integrated terminal at the bottom for running CLI agents (Claude Code, Codex, Aider). They write YAML directly, get instant visual feedback, and version-control everything with git. Launched via `pip install charter[studio]` → `charter dev` → browser opens. Optionally wrapped in a native macOS app via Tauri.

**Business Users** use natural language prompts (in the future hosted web app). The LLM translates their request into the same YAML DSL. Because the DSL vocabulary is small and the output structure is rigid, this is a much more reliable translation task than generating raw Vega-Lite. The validation layer catches schema errors and prompts the LLM for corrections before anything reaches the renderer.

Both user types converge on the same intermediate representation (the YAML DSL) and the same deterministic translation pipeline. This is the "two entry points, one pipeline" architecture.

## Implementation Roadmap

### Phase 1: Core Chart Pipeline (In Progress)
- Chart DSL → Pydantic validation → Vega-Lite translation → theme merge → data bind → HTML render
- Single-measure charts: bar, line, area, scatter, heatmap, pie, point, tick, KPI
- Multi-measure stacked panels (repeat/vconcat)
- All encoding channels: color, detail, size, tooltip, sort
- Shelf filters: in, not_in, eq, neq, gt, lt, gte, lte, between
- Faceting: row, column, grid, wrap (combinable with all above)
- CLI: `charter render chart.yaml -o chart.html`
- Status: Bootstrap, schema, core translator, theme, data bind, render, CLI all done. Multi-measure stacked panels in progress.

### Phase 1a: Layers (Multi-Axis)
- `layer` property on MeasureEntry for overlaid marks
- Independent/shared scale resolution
- Stacked layers pattern (panels where some have layers)
- Triple/quad axis (N layers, no cap)

### Phase 2: Theme Pipeline
- Figma → Style Dictionary → Vega-Lite config automated pipeline
- Dark mode / multi-brand theming via token set swapping

### Phase 3: Semantic Layer Integration
- Cube.dev connection: chart DSL metric references → Cube API calls
- Data flow: prompt → DSL → Cube query → data + spec → render

### Phase 4: Layout DSL + Dashboard
- Layout DSL → CSS flexbox translator
- Dashboard composition: nested containers, sheets, text, images, navigation
- Static output first; interactive filters deferred

### Phase 5: Charter Studio
- Local dev server: FastAPI + Monaco editor + live Vega-Lite preview + integrated terminal
- Dashboard composition view for Layout DSL editing
- File explorer sidebar
- Optional Tauri native macOS app wrapper (Stage 2)

### Phase 6: Web Application
- Hosted version for business users
- Natural language prompt UI
- State management for filter propagation and dashboard sessions

### Phase 7: Production Hardening
- VegaFusion for server-side scaling
- YAML schema validation (pre-LLM-output validation layer)
- Caching for common prompt → YAML translations
- Auth, multi-tenancy, and data access controls

## Strategic Positioning

Charter fills five identified gaps in the current BI landscape:

1. **A purpose-built intermediate DSL** between natural language and rendering — no other platform has a formal, constrained intermediate representation designed for both human authoring and LLM generation.
2. **The Tableau shelf model formalized as a code-first grammar** — familiar vocabulary, but version-controlled, diffable, and reviewable.
3. **An automated Figma-to-Vega-Lite theme pipeline** — design token changes propagate automatically to every chart, something Tableau's theming cannot do.
4. **A dual-entry-point architecture** — analyst YAML and business-user natural language converge into the same pipeline, the same validation, the same rendering.
5. **Fully version-controllable BI** — no opaque GUI state, no fragile workbook files, no drag-and-drop serialization formats.

Key competitive risks to monitor: Holistics (YAML scalability critique), Hex (closest competitor in the code-first BI space).

## Challenges and Risks

- **DSL Grammar Completeness:** The chart pattern catalog must cover the most common BI visualizations. Edge cases (treemaps, Sankey diagrams, advanced geographic maps) may require dropping down to raw Vega or custom extensions. The grammar should be designed to be extensible.
- **LLM Schema Adherence:** System prompts must be carefully engineered with extensive examples to ensure the LLM strictly adheres to the DSL grammar. A validation layer between LLM output and the translator is essential — if the YAML fails validation, the error is fed back to the LLM for correction.
- **App Architecture & State Management:** Wiring together frontend state (filter propagation across charts, dashboard sessions, saving configurations, user auth) is a significant engineering effort. Using application-level state management for filter propagation is recommended over composing all charts into a single Vega spec.
- **Semantic Layer Setup:** Defining initial data models and metrics in Cube.dev or dbt requires upfront data engineering work. The quality of the semantic layer directly constrains the quality of the AI-generated charts.
- **Complex Compositions:** Layered multi-axis charts faceted by region with independent y-scales generate deeply nested Vega-Lite specs. The translator must handle these combinations correctly — a comprehensive test suite of DSL → Vega-Lite pairs is critical.

## Technology Stack

| Layer | Technology | Role |
|---|---|---|
| **Core Pipeline** | Python, Pydantic, PyYAML | YAML parse, validation, translation |
| **Data / Semantic** | Cube.dev (or dbt Semantic Layer, Malloy) | Metric definitions, aggregation, API |
| **Chart DSL** | Custom YAML schema | Tableau-like shelf grammar for chart definitions |
| **Layout DSL** | Custom YAML schema | Nested container grammar for dashboard structure |
| **Theme** | Figma + Style Dictionary + custom formatter | Automated design token → Vega-Lite config pipeline |
| **Chart Rendering** | Vega-Lite (Canvas mode) | Declarative chart compilation and rendering |
| **Server-side Scaling** | VegaFusion | Pushes transforms/aggregation to server |
| **LLM** | Claude / GPT-4 / Gemini | Translates natural language → YAML DSL |
| **Analyst Interface** | Charter Studio (FastAPI + Monaco + Vega-Lite preview) | Local dev server with live preview and integrated terminal |
| **Native App** | Tauri v2 (optional) | macOS wrapper around Charter Studio |
| **Config Format** | YAML (authored) / JSON (compiled) | Human-readable authoring, machine-readable execution |
| **Version Control** | GitHub | All configs (charts, layouts, themes, semantic models) are code |
| **Testing** | pytest + syrupy (snapshot testing) | DSL → Vega-Lite pair validation |
| **AI Tooling** | Claude Code (MCP), GitHub Copilot | Development workflow |
| **Project Management** | Jira Cloud | Ticket tracking, epic planning |
