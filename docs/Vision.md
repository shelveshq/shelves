# Project Vision: AI-Native Declarative Visual Analytics Platform

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
- **Per-mark encoding for dual axis charts.** Each measure in a multi-measure chart can have independent mark types (`bar` + `dashed line`), colors (`country` + `"#666666"`), and detail levels (`country` + `null`). The tuple ordering matches the measures list.
- **Semantic layer references only.** Fields like `revenue` and `country` are names from the semantic layer menu — never raw SQL, column expressions, or calculated fields.
- **No styling.** The theme layer handles all visual aesthetics. The LLM cannot hallucinate off-brand colors.

### Layout DSL — Where to place it

A dashboard composition grammar based on Tableau's nested container model. Dashboards are trees of horizontal and vertical flex containers holding chart sheets, filter panes, text blocks, and spacers.

Key design decisions:
- **Fixed canvas size** (e.g., 1440×900px) eliminates responsive design complexity in v1.
- **Filters are first-class layout components** with a `targets` property controlling which charts they affect (`all` or a named list).
- **Sheet references link to chart specs** — the layout defines *where* things go, chart YAMLs define *what* each chart looks like, and the theme defines *how* everything is styled. Three independent, version-controllable layers.
- **Deterministic CSS flexbox translation.** Vertical container → `flex-direction: column`, horizontal → `row`. No ambiguity.

## Five-Layer Architecture

### 1. Semantic Data Layer (Cube.dev / dbt Semantic Layer / Malloy)

The single source of truth for all business logic. Defines metrics, dimensions, joins, and access controls as code. The LLM picks from a fixed "menu" of available metrics — it cannot hallucinate SQL, invent columns, or miscalculate business logic.

This layer is also the primary performance optimization: all aggregation happens server-side. A chart showing weekly revenue by country across 10 million transactions sends ~500 aggregated rows to the browser, not 10 million.

### 2. Chart DSL Layer

The YAML grammar translating Tableau's shelf model into a structured, machine-readable format. Each YAML file defines one chart. The DSL-to-Vega-Lite translator handles a finite catalog of chart patterns (simple bar, dual axis, faceted views, KPIs, scatter with trend lines, etc.), each implemented as a deterministic "recipe."

### 3. Layout DSL Layer

The YAML grammar for dashboard composition. Nested containers, chart references, filter panes with targeting, text blocks, and spacers — all translating deterministically to CSS flexbox.

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

**BI Analysts** write the YAML DSL directly. They think in Tableau's mental model and get version-controlled, diffable, reviewable chart definitions without learning Vega-Lite syntax. Changes are made by editing YAML — no drag-and-drop, no fragile workbook state.

**Business Users** use natural language prompts. The LLM translates their request into the same YAML DSL. Because the DSL vocabulary is small and the output structure is rigid, this is a much more reliable translation task than generating raw Vega-Lite. The validation layer catches schema errors and prompts the LLM for corrections before anything reaches the renderer.

## Implementation Roadmap

### Phase 1: Single Chart PoC
- Hardcoded prompt → LLM → chart YAML DSL → Vega-Lite spec → rendered HTML
- Validate the DSL grammar against 5–10 common chart types (bar, line, dual axis, scatter, KPI)
- Use inline data (no semantic layer yet)

### Phase 2: Theme Integration
- Create a sample `theme.json` manually (mimicking Figma output structure)
- Merge theme into chart specs before rendering
- Validate visual consistency across chart types

### Phase 3: Semantic Layer Integration
- Set up basic Cube.dev instance with sample data models
- Connect chart DSL metric references to Cube.dev API calls
- Validate data flow: prompt → DSL → Cube query → data + spec → render

### Phase 4: Layout DSL + Dashboard
- Implement layout DSL → flexbox translator
- Compose multiple charts into a single dashboard page
- Add filter panes with cross-chart targeting via application state

### Phase 5: Figma Theme Pipeline
- Set up Figma → export plugin → Style Dictionary → custom Vega-Lite formatter
- Validate end-to-end: Figma token change → regenerated theme → updated dashboard

### Phase 6: Web Application
- Wrap the pipeline in a frontend framework (Next.js or Vite)
- Add user interface for prompt input, dashboard navigation, and configuration
- Implement state management for filter propagation and dashboard sessions

### Phase 7: Production Hardening
- Add VegaFusion for server-side scaling
- Implement YAML schema validation (pre-LLM-output validation layer)
- Add caching for common prompt → YAML translations
- Implement auth, multi-tenancy, and data access controls

## Challenges and Risks

- **DSL Grammar Completeness:** The chart pattern catalog must cover the most common BI visualizations. Edge cases (treemaps, Sankey diagrams, advanced geographic maps) may require dropping down to raw Vega or custom extensions. The grammar should be designed to be extensible.
- **LLM Schema Adherence:** System prompts must be carefully engineered with extensive examples to ensure the LLM strictly adheres to the DSL grammar. A validation layer between LLM output and the translator is essential — if the YAML fails validation, the error is fed back to the LLM for correction.
- **App Architecture & State Management:** Wiring together frontend state (filter propagation across charts, dashboard sessions, saving configurations, user auth) is a significant engineering effort. Using application-level state management (React state) for filter propagation is recommended over composing all charts into a single Vega spec.
- **Semantic Layer Setup:** Defining initial data models and metrics in Cube.dev or dbt requires upfront data engineering work. The quality of the semantic layer directly constrains the quality of the AI-generated charts.
- **Facet + Dual Axis Combinations:** Complex compositions (e.g., a dual-axis layered chart faceted by region with independent y-scales) generate deeply nested Vega-Lite specs. The translator must handle these combinations correctly — a comprehensive test suite of DSL → Vega-Lite pairs is critical.

## Technology Stack

| Layer | Technology | Role |
|---|---|---|
| **Data / Semantic** | Cube.dev (or dbt Semantic Layer, Malloy) | Metric definitions, aggregation, API |
| **Chart DSL** | Custom YAML schema | Tableau-like shelf grammar for chart definitions |
| **Layout DSL** | Custom YAML schema | Nested container grammar for dashboard structure |
| **Theme** | Figma + Style Dictionary + custom formatter | Automated design token → Vega-Lite config pipeline |
| **Chart Rendering** | Vega-Lite (Canvas mode) | Declarative chart compilation and rendering |
| **Server-side Scaling** | VegaFusion | Pushes transforms/aggregation to server |
| **LLM** | Claude / GPT-4 / Gemini | Translates natural language → YAML DSL |
| **Config Format** | YAML (authored) / JSON (compiled) | Human-readable authoring, machine-readable execution |
| **Version Control** | GitHub | All configs (charts, layouts, themes, semantic models) are code |
| **Frontend** | Next.js / Vite (TBD) | Web application wrapper |