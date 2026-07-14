# Docs — CLAUDE.md

## Structure

- `guide/` — User-facing documentation
  - `dsl-reference.md` — Complete DSL field/property reference with examples and type tables
  - `getting-started.md` — Introductory workflow and basic examples
  - `dashboards.md` — Dashboard / Layout DSL guide
- `foundational/` — Architecture, design, and strategy documents (Vision, DSL/MCP/Template/Parameter/LLM-Writability specifications, Market Landscape, Positioning, Pitch). **Local-only: gitignored, never committed** — like `plans/`, these live on the founder's machine and are not published.
- `plans/` — Implementation plans for specific tickets (KAN-xxx.md)

## Rules

- **DSL changes require doc updates.** Any change to `shelves/schema/chart_schema.py` MUST be accompanied by updates to `guide/dsl-reference.md` and (if applicable) `guide/getting-started.md`. See `shelves/schema/CLAUDE.md` for the full list of what triggers this.
- **Foundational docs are reference material.** They describe the overall vision and architecture. Update them only when the project direction or high-level architecture changes — not for incremental feature work.
- **Plans are ephemeral and MUST NEVER be committed.** They capture implementation strategy for a specific ticket and don't need to be kept in sync with code after the work is done. `docs/plans/` is gitignored (`.gitignore`) and must stay that way — never remove that entry, and never force-add a plan with `git add -f`. Plans are local working artifacts only; they are not published to the repo, ever. If you find a `docs/plans/*.md` file tracked by git, untrack it (`git rm --cached`).
