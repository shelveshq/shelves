# Architecture: Charter — AI-Native Declarative Visual Analytics Platform

## 1. System Overview

This document defines the complete architecture for an enterprise-grade visual analytics platform that replaces traditional drag-and-drop BI interfaces with AI-assisted natural language. The system uses a layered, declarative approach where every component — data logic, chart structure, dashboard layout, and visual styling — is expressed as structured configuration (YAML/JSON), version-controlled via GitHub, and deterministically translated into interactive web visualizations.

### 1.1 Core Architectural Principle

The LLM never generates code. It generates structured YAML configurations within a tightly constrained schema. Every downstream translation — from YAML to Vega-Lite spec, from design tokens to theme JSON, from layout DSL to CSS flexbox — is deterministic. This minimizes the surface area for errors and makes the system auditable, diffable, and debuggable.

### 1.2 High-Level Data Flow

```
User Input (natural language or DSL)
        │
        ▼
┌─────────────────────┐
│   LLM Router        │  Translates prompt → YAML DSL
│   (Claude / GPT-4)  │  OR: Analyst writes YAML directly
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐     ┌──────────────────────┐
│  Chart YAML Specs   │     │  Layout YAML Spec    │
│  (per-sheet DSL)    │     │  (dashboard DSL)     │
└────────┬────────────┘     └────────┬─────────────┘
         │                           │
         ▼                           ▼
┌─────────────────────┐     ┌──────────────────────┐
│ YAML → Vega-Lite    │     │ YAML → Flex/CSS      │
│ Translator (code)   │     │ Translator (code)    │
└────────┬────────────┘     └────────┬─────────────┘
         │                           │
         ▼                           ▼
┌─────────────────────┐     ┌──────────────────────┐
│ Vega-Lite Spec      │     │ Dashboard Container  │
│ + Theme JSON merge  │     │ (HTML/CSS flexbox)   │
└────────┬────────────┘     └────────┬─────────────┘
         │                           │
         ▼                           ▼
┌──────────────────────────────────────────────────┐
│              Rendering Engine                     │
│   Vega-Lite embeds inside flex containers         │
│   Data fetched from Semantic Layer (Cube.dev)     │
│   Theme merged at render time                     │
│   Canvas renderer (default) for performance       │
└──────────────────────────────────────────────────┘
```

### 1.3 Two Entry Points, One Pipeline

The system serves two user types through the same underlying pipeline:

- **BI Analysts** use Charter Studio — a local dev server with Monaco editor, live Vega-Lite preview, and integrated terminal. They write the YAML DSL directly, get instant visual feedback, and version-control with git.
- **Business Users** use natural language prompts (in the future hosted web app). The LLM translates their request into the same YAML DSL. The LLM's job is constrained to producing valid DSL — a much smaller, more reliable translation task than generating raw Vega-Lite.

---

## 2. Layer Architecture

### 2.1 Semantic Data Layer (Cube.dev / dbt Semantic Layer / Malloy)

The semantic layer is the single source of truth for all business logic. It defines metrics, dimensions, joins, and access controls as code (YAML). The LLM and the chart DSL reference metrics by name — they never write SQL or perform calculations.

**Responsibilities:**
- Define metrics (e.g., "Revenue", "ARPU", "Active Users") with their aggregation logic
- Define dimensions (e.g., "Country", "Week", "Product Category") with their source columns
- Define joins between data models
- Expose a clean API that accepts metric/dimension requests and returns aggregated tabular data
- Handle row-level security and data access controls

**Why this matters for performance:** The semantic layer performs all aggregation server-side. A chart showing weekly revenue by country across 10 million transactions sends ~500 aggregated rows to the browser, not 10 million raw rows. This is the single biggest performance optimization in the architecture.

**Why this matters for AI reliability:** The LLM picks from a fixed "menu" of available metrics and dimensions. It cannot hallucinate SQL, invent columns that don't exist, or miscalculate business logic. If the semantic layer doesn't expose a metric, the LLM can't request it.

### 2.2 Chart DSL Layer

The chart DSL is a YAML grammar inspired by Tableau's shelf model (rows, columns, marks, color, detail, filters). It is the intermediate representation between user intent and Vega-Lite specification. See the **DSL Specification** document for the full grammar.

**Key design decisions:**
- Uses Tableau terminology (rows, cols, marks, color, detail) because BI analysts already think this way
- `rows` and `cols` are exclusively for axis encoding (x/y); chart partitioning uses a separate `facet` property — this is cleaner than Tableau where shelves serve double duty
- Multi-measure shelves use per-measure `MeasureEntry` objects (not parallel arrays) — each measure carries its own mark, color, detail, size, and opacity
- Layers nest inside measure entries via a `layer` property for multi-axis overlay charts
- Encoding properties cascade: top-level → measure entry → layer entry (more specific wins)
- At most one of rows/cols can be a multi-measure list (no 2×2 ambiguity)
- References semantic layer metrics/dimensions by name
- Does not contain any styling information — that comes from the theme layer
- Does not contain any layout information — that comes from the layout DSL

### 2.3 Layout DSL Layer

The layout DSL defines dashboard structure as nested horizontal and vertical containers — the same mental model as Tableau dashboards. It references chart specs by name and defines text blocks, images, navigation elements, and spacers. See the **Layout DSL Specification** document for the full grammar.

**Key design decisions:**
- Dashboards are authored at a fixed pixel size (e.g., 1440×900) to eliminate responsive design complexity in v1
- Containers are either horizontal or vertical, and nest arbitrarily deep
- The tree IS the layout — containers define children inline via `contains`
- Three ways to place a child: string reference, inline anonymous, inline named
- Shared styles with inline overrides; `html` escape hatch for raw CSS
- Sheet references link to chart YAML files — layout, chart, and theme are three independent layers
- Static output in v1 (no interactive filters); navigation is the only "interactive" element
- Translates deterministically to CSS flexbox

### 2.4 Theme Layer (Figma → Style Dictionary → Vega-Lite Config)

The theme is a global JSON configuration object that controls all visual aesthetics. It is generated from Figma design tokens via an automated pipeline and merged with every Vega-Lite spec at render time. The LLM never touches it.

**Pipeline:**

```
Figma Design System
        │
        ▼  (Figma export plugin — W3C Design Tokens Format)
Design Tokens JSON
        │
        ▼  (Style Dictionary — custom Vega-Lite formatter)
Vega-Lite config JSON (theme.json)
        │
        ▼  (merged at render time)
Every chart spec inherits the theme
```

**Token-to-Vega-Lite Mapping (deterministic, not AI-driven):**

| Figma Token | Vega-Lite Config Property |
|---|---|
| `color.primary.500` | `mark.color`, `range.category[0]` |
| `color.primary.[500,400,300...]` + `color.secondary.[...]` | `range.category` (full palette) |
| `color.background` | `background` |
| `color.surface` | `view.fill` |
| `color.neutral.200` | `axis.gridColor` |
| `color.neutral.400` | `axis.domainColor`, `axis.tickColor` |
| `color.text.primary` | `axis.labelColor`, `title.color`, `legend.labelColor` |
| `color.text.secondary` | `axis.titleColor`, `legend.titleColor` |
| `font.family.body` | `axis.labelFont`, `legend.labelFont` |
| `font.family.heading` | `title.font`, `header.titleFont` |
| `font.size.xs` | `legend.labelFontSize` |
| `font.size.sm` | `axis.labelFontSize` |
| `font.size.md` | `axis.titleFontSize`, `legend.titleFontSize` |
| `font.size.lg` | `title.fontSize` |
| `font.weight.normal` | `axis.labelFontWeight` |
| `font.weight.bold` | `title.fontWeight` |
| `spacing.sm` | `legend.padding` |
| `spacing.md` | `padding` (chart padding) |
| `border.radius.sm` | `bar.cornerRadius`, `rect.cornerRadius` |

This mapping is codified once in a custom Style Dictionary formatter function. When a designer updates colors in Figma, the pipeline regenerates `theme.json` automatically. No AI involved.

### 2.5 Rendering Layer (Vega-Lite + VegaFusion)

The rendering layer takes compiled Vega-Lite specs, merges them with the theme, binds data from the semantic layer, and renders interactive charts via HTML5 Canvas.

**Performance architecture:**

1. **Semantic layer pre-aggregation:** All GROUP BY, binning, and metric calculations happen server-side in Cube.dev. Only aggregated results reach the browser.
2. **VegaFusion server-side scaling:** For any remaining transforms (window functions, cross-filter recalculations), VegaFusion partitions computation between server and client. The browser never receives raw data.
3. **Canvas rendering (default):** Canvas is 2–10x faster than SVG for redraws. SVG is available as an export option for print-quality output.
4. **Practical limits:** With pre-aggregation, the browser typically handles hundreds to low thousands of data points per chart — well within Vega-Lite's comfortable performance range (~10,000 points).

---

## 3. Tableau → Vega-Lite Concept Mapping

The chart DSL is designed around Tableau's mental model. This table documents how core Tableau concepts translate to Vega-Lite constructs. The DSL-to-Vega-Lite translator implements these mappings as deterministic code.

### 3.1 Shelf Model

In the DSL, `cols` and `rows` are exclusively for axis encoding (what goes on x and y). Chart partitioning into small multiples is handled by a separate `facet` property. This avoids the ambiguity in Tableau where the Rows/Columns shelves serve double duty for both axis assignment and view partitioning.

| DSL Concept | Vega-Lite Equivalent | Notes |
|---|---|---|
| **`cols`** (dimension or measure) | `x` encoding channel | Always an axis assignment, never partitioning |
| **`rows`** (dimension or measure) | `y` encoding channel | Always an axis assignment, never partitioning |
| **`rows`** (list of MeasureEntry) | `repeat`/`vconcat`/`layer` | Multi-measure: stacked panels, layers, or mixed |
| **`facet.row`** (dimension) | `row` encoding / `facet` operator | Partitions chart into vertical small multiples |
| **`facet.column`** (dimension) | `column` encoding / `facet` operator | Partitions chart into horizontal small multiples |
| **`facet.wrap`** (dimension + columns) | `facet` operator with `columns` param | Wrapping grid of small multiples |
| **Measure Values / Names** | `fold` transform + encode on `key`/`value` | Reshapes wide data to long format |

### 3.2 Multi-Measure (Dual/Multi-Axis)

| DSL Pattern | Vega-Lite Equivalent |
|---|---|
| Entry with `layer` list (overlaid measures) | `layer` spec — multiple marks sharing `x`, separate `y` encodings |
| `axis: shared` (default) | `resolve: { scale: { y: "shared" } }` |
| `axis: independent` | `resolve: { scale: { y: "independent" } }` |
| Per-entry mark types | Each layer has its own `mark` definition |
| Stacked panels (no layers) | `repeat` (same marks) or `vconcat` (mixed marks) |
| Stacked layers (mixed entries) | `vconcat` of `layer` specs and simple specs |

### 3.3 Marks Card

| Tableau Mark | Vega-Lite Mark | Notes |
|---|---|---|
| Bar | `bar` | |
| Line | `line` | Dashed: `strokeDash: [6, 4]` |
| Circle | `circle` | |
| Square | `square` | |
| Area | `area` | |
| Text | `text` | Usually as a layer on top of another mark |
| Map | `geoshape` | Requires TopoJSON/GeoJSON data |

### 3.4 Encoding Channels

| Tableau Card | Vega-Lite Channel | Behavior |
|---|---|---|
| **Color** | `color` | Maps field to color scale (categorical or sequential) |
| **Size** | `size` | Maps field to mark size |
| **Detail** | `detail` | Disaggregates marks without visual encoding (identical concept) |
| **Label / Text** | `text` | Typically via a `text` mark layer |
| **Tooltip** | `tooltip` | Supports multiple fields as array |
| **Shape** | `shape` | For point marks |

### 3.5 Filters

| Tableau Filter Type | Vega-Lite Equivalent |
|---|---|
| Shelf filter (hardcoded) | `transform: [{ filter: ... }]` |
| Quick filter (dropdown) | `params` with `select: point` + `bind: { input: select }` |
| Quick filter (slider/range) | `params` with `select: interval` + `bind: { input: range }` |
| Quick filter (radio/checkbox) | `params` with `bind: { input: radio }` or `checkbox` |
| "Use as Filter" action (cross-filtering) | Shared `params` across views in `concat`/`vconcat` spec |
| Filter targets (specific sheets) | `params` defined at the appropriate composition level |

### 3.6 Other Concepts

| Tableau Concept | Vega-Lite Equivalent | Notes |
|---|---|---|
| **Sorting** | `sort` property on encoding | By field value, aggregate, or explicit order |
| **Table Calculations** (running total, moving avg) | `window` transform | Covers most common cases |
| **LOD Expressions** (FIXED, INCLUDE, EXCLUDE) | **Semantic layer** | Better handled in Cube.dev, not in chart spec |
| **Pages shelf** (animation) | No native equivalent | Simulate with param-bound slider + filter |
| **Reference lines** | `layer` with `rule` mark | Horizontal/vertical reference lines |
| **Trend lines** | `layer` with `regression` transform + `line` mark | |
| **Sets** | `calculate` transform + conditional logic | Or pre-computed in semantic layer |

---

## 4. Performance Strategy

### 4.1 Performance Bottlenecks and Mitigations

| Bottleneck | Mitigation | Owner |
|---|---|---|
| Raw data volume in browser | Pre-aggregate in semantic layer; browser receives hundreds of rows, not millions | Semantic Layer (Cube.dev) |
| Client-side transform computation | VegaFusion pushes transforms to server-side Rust runtime | VegaFusion |
| Rendering speed (DOM overhead) | Canvas renderer by default (2–10x faster than SVG) | Rendering config |
| Large scatterplots (no aggregation possible) | Density heatmap conversion; sampling transform | Chart DSL / Translator |
| Cross-filter recalculation on interaction | VegaFusion caches intermediate results; only recomputes changed branches | VegaFusion |
| LLM response latency | Cache common prompt→YAML translations; stream partial results | Application layer |

### 4.2 Data Flow Performance Model

```
Database (millions of rows)
    │
    ▼  SQL query with GROUP BY (Cube.dev)
Aggregated result (~100-5,000 rows)
    │
    ▼  JSON API response
Browser receives small payload
    │
    ▼  VegaFusion handles any remaining transforms server-side
Minimal data reaches Vega-Lite renderer
    │
    ▼  Canvas rendering
Interactive chart in <100ms render time
```

### 4.3 When Vega-Lite Struggles

Vega-Lite's comfortable interactive performance range is approximately 10,000 data points per chart. Beyond 30,000 points, interactions become sluggish. This is rarely an issue for BI dashboards because:

- Bar charts, line charts, and area charts are aggregated by definition
- KPI sheets display single values
- The only problematic case is raw scatterplots of unaggregated data — these should be converted to density heatmaps or sampled

---

## 5. Figma → Vega-Lite Theme Pipeline (Detail)

### 5.1 Pipeline Steps

1. **Design in Figma:** Designers define colors, typography, spacing, and border radius as Figma Variables organized into collections (e.g., "Primitives", "Semantic", "Component").

2. **Export from Figma:** Use a design tokens export plugin (e.g., Design Tokens Manager, Tokens Studio) to export variables as JSON following the W3C Design Tokens Format specification.

3. **Transform with Style Dictionary:** Style Dictionary reads the exported JSON tokens and runs them through a custom formatter that outputs valid Vega-Lite `config` JSON.

4. **Output `theme.json`:** The formatter maps each token category to the corresponding Vega-Lite config property (see mapping table in Section 2.4). The output is a complete Vega-Lite config object.

5. **Merge at render time:** The web application loads `theme.json` once and merges it into every Vega-Lite spec before rendering.

### 5.2 Competitive Advantage

Tableau's theming is notoriously difficult to maintain. Workbook-level formatting is fragile, server-level defaults require admin access, and there is no automated pipeline from design tools to chart styles. This platform's Figma → Vega-Lite pipeline means:

- Designers update tokens in Figma → theme regenerates automatically → all dashboards update
- Brand consistency is enforced by the system, not by individual authors
- Dark mode / multi-brand theming is just a different token set through the same pipeline

### 5.3 Example Style Dictionary Custom Formatter

```javascript
// Pseudocode for the custom Vega-Lite formatter
StyleDictionary.registerFormat({
  name: 'vegaLiteConfig',
  formatter: ({ dictionary }) => {
    const tokens = dictionary.tokens;
    return JSON.stringify({
      background: tokens.color.background.value,
      mark: { color: tokens.color.primary['500'].value },
      title: {
        font: tokens.font.family.heading.value,
        fontSize: tokens.font.size.lg.value,
        fontWeight: tokens.font.weight.bold.value,
        color: tokens.color.text.primary.value
      },
      axis: {
        labelFont: tokens.font.family.body.value,
        labelFontSize: tokens.font.size.sm.value,
        labelColor: tokens.color.text.primary.value,
        titleFont: tokens.font.family.body.value,
        titleFontSize: tokens.font.size.md.value,
        titleColor: tokens.color.text.secondary.value,
        gridColor: tokens.color.neutral['200'].value,
        domainColor: tokens.color.neutral['400'].value,
        tickColor: tokens.color.neutral['400'].value
      },
      legend: {
        labelFont: tokens.font.family.body.value,
        labelFontSize: tokens.font.size.xs.value,
        titleFont: tokens.font.family.body.value,
        titleFontSize: tokens.font.size.md.value
      },
      range: {
        category: [
          tokens.color.primary['500'].value,
          tokens.color.secondary['500'].value,
          tokens.color.accent['500'].value,
          // ... additional palette colors
        ]
      },
      bar: { cornerRadius: tokens.border.radius.sm.value },
      view: { fill: tokens.color.surface.value }
    }, null, 2);
  }
});
```

---

## 6. Charter Studio — Analyst Interface

Charter Studio is the analyst-facing authoring environment: a local dev server with a split-pane HTML interface launched via `charter dev`. See the **Charter Studio Design** document for the full specification.

**Architecture:**
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

**Key decisions:**
- Monaco editor via CDN (not a VS Code extension or fork) — provides full editor UX without framework dependencies
- Real PTY-backed terminal, not a custom AI chat UI — tool-agnostic, works with any CLI agent
- Single HTML page, no build step, no React, no `node_modules`
- Optional Tauri v2 native macOS app wrapper (Stage 2) — uses WebKit, ~5MB bundle vs Electron's 150MB+
- The web app (Phase 6) and Charter Studio coexist as two entry points for different user types

---

## 7. Technology Stack Summary

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

---

## 8. Implementation Roadmap

### Phase 1: Core Chart Pipeline (In Progress)
- Chart DSL → Pydantic → Vega-Lite → theme merge → data bind → HTML render
- Single-measure charts + multi-measure stacked panels
- All encoding channels, filters, sort, faceting
- CLI: `charter render chart.yaml -o chart.html`

### Phase 1a: Layers (Multi-Axis)
- Layer compilation, stacked layers, triple/quad axis
- Encoding inheritance resolution

### Phase 2: Theme Pipeline
- Figma → Style Dictionary → Vega-Lite config
- Dark mode / multi-brand theming

### Phase 3: Semantic Layer Integration
- Cube.dev connection: chart DSL metric references → Cube API calls
- Data flow: prompt → DSL → Cube query → data + spec → render

### Phase 4: Layout DSL + Dashboard
- Layout DSL → CSS flexbox translator
- Static dashboard composition

### Phase 5: Charter Studio
- Local dev server: FastAPI + Monaco + live preview + terminal
- Optional Tauri native app

### Phase 6: Web Application
- Hosted version for business users
- Natural language prompt UI
- State management for dashboard sessions

### Phase 7: Production Hardening
- VegaFusion for server-side scaling
- YAML schema validation
- Caching, auth, multi-tenancy
