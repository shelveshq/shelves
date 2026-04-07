# Docs — CLAUDE.md

## Structure

- `guide/` — User-facing documentation
  - `dsl-reference.md` — Complete DSL field/property reference with examples and type tables
  - `getting-started.md` — Introductory workflow and basic examples
- `foundational/` — Architecture and design documents (Vision, Architecture, DSL Specifications, Measure Design)
- `plans/` — Implementation plans for specific tickets (KAN-xxx.md)

## Rules

- **DSL changes require doc updates.** Any change to `shelves/schema/chart_schema.py` MUST be accompanied by updates to `guide/dsl-reference.md` and (if applicable) `guide/getting-started.md`. See `shelves/schema/CLAUDE.md` for the full list of what triggers this.
- **Foundational docs are reference material.** They describe the overall vision and architecture. Update them only when the project direction or high-level architecture changes — not for incremental feature work.
- **Plans are ephemeral.** They capture implementation strategy for a specific ticket. They don't need to be kept in sync with code after the work is done.
