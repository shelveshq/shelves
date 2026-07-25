# Params — CLAUDE.md

Parameters are a **project-level entity**, not chart DSL. They are declared
once in `parameters.yaml` beside the semantic models and referenced from charts
with `$name`. Nothing parameter-shaped ever reaches `ChartSpec` — the
substitution pass runs before Pydantic and leaves an ordinary chart behind.

## Files

- `schema.py` — `ParameterDef` union (`string`/`number`/`date`/`field`) and the
  `values:` entry types (`FieldRef`, `RangeBounds`, plus bare literals)
- `loader.py` — `load_parameters()`; default `<models_dir>/parameters.yaml`.
  **A missing file returns `{}`, never raises**
- `refs.py` — `$name` (whole-scalar only) and `${name}` recognition; `$$` escape
- `positions.py` — the **allow-list** of paths where a reference is legal
- `substitute.py` — `ParameterSet` (declarations + resolved values) and the walk

## Key Rules

- **The allow-list is exhaustive.** `classify()` returns `None` for unlisted
  paths and `None` means forbidden. When a new DSL field lands, parameters are
  rejected there until someone adds it to `positions.py` deliberately. Never
  default unknown paths to allowed.
- **Reference problems are collected, not raised.** The walk returns
  diagnostics; the caller decides. This is what lets a future template pass run
  ahead of substitution and consume its own refs first.
- **No dead-parameter lint.** Parameters are project-level — one unused by this
  chart may be used by another.
- **Null prunes filters.** `ShelfFilter`'s validator raises when an operator's
  required value key is `None`, so a null-valued filter must be dropped before
  Pydantic sees it.
- **Every model reference is explicit.** The file has no ambient model context.
  Field names stay bare (grain suffixes allowed); there is no `model.field`
  dotted form.
- **`values:` is always a list.** Entry kind is dispatched by key presence —
  `model` → `FieldRef`, `min`+`max` → `RangeBounds`, scalar → literal. A list
  must be homogeneous, and a range must be the only entry.

## Gotchas

- Pydantic runs base-class `mode="after"` validators on subclasses.
  `_literal_types_take_one_ref` is gated on `self.type != "field"` for exactly
  this reason — without the guard it fires on the most common parameter shape.
- The `mode="before"` `_coerce_values` hook exists so a non-list `values:`
  produces the "write entries with YAML dashes" message rather than a generic
  Pydantic type error. Omitting the dash is the likeliest authoring slip.
- YAML turns an unquoted ISO date into a `datetime.date`, so `RangeBounds`
  bounds accept `dt.date` alongside `str` and numbers.
