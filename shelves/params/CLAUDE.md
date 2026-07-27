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
- `coerce.py` — raw string → declared-type coercion for overrides
  (`parse_param_flags`, `coerce_override`, `describe_values`). Coercion NEVER
  validates; `ParameterSet` owns that
- `resolve.py` — `load_parameter_set()`, the **single builder every surface
  calls**. Loads the file, resolves SHE-90 domains, coerces overrides,
  constructs the `ParameterSet`
- Domain resolution lives OUTSIDE this package, in `shelves/data/domains.py` — it needs a model resolver and a live data connection, which is a data-layer concern. `schema.py` stores a `FieldRef` and never dereferences it.

## Key Rules

- **Surfaces never construct a `ParameterSet` by hand.** The render CLI, dev
  CLI, and both Studio compile paths call
  `shelves.params.resolve.load_parameter_set`. That is what makes the four
  surfaces behave identically — parity by construction, not by four call sites
  that happen to agree. It is also the only call site of
  `shelves.data.domains.resolve_parameter_domains`.
- **`models_dir` and `data_base_dir` travel together.** A surface passes
  `load_parameter_set` the same pair it passes `resolve_model_data` /
  `compile_dashboard_charts`. Splitting them validates a value against one
  dataset and charts rows from another.
- **The pipeline never reads a parameters file.**
  `compile_chart(parameters=None)` means `ParameterSet.empty()`, not "go find
  `<models_dir>/parameters.yaml`". Auto-loading would silently change the
  meaning of every existing chart compiled with a `models_dir` that happens to
  contain one.
- **Coercion is driven by the declared `type`, never by the string's content.**
  `--param status=10` stays the string `"10"` because `status` is
  `type: string`. An override naming an undeclared parameter is passed through
  coercion untouched so `ParameterSet` can own that one error message.
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
- **`validate_value` (schema.py) enforces literal and range constraints only.**
  A field-reference domain is checked by
  `shelves.data.domains.check_value_in_domain`, which needs the resolved
  `Domain`. Two functions, two constraint families — do not merge them.
- **`type: field` never touches data.** Its `values:` are field *names*, checked
  against the model manifest by `load_parameters(validate_fields=True)`. The one
  exception is a bare `{model: X}` entry ("any field in that model"), whose
  `default` is checked against the manifest by `resolve_parameter_domains` —
  still a manifest read, still no query.

## Gotchas

- Pydantic runs base-class `mode="after"` validators on subclasses.
  `_literal_types_take_one_ref` is gated on `self.type != "field"` for exactly
  this reason — without the guard it fires on the most common parameter shape.
- The `mode="before"` `_coerce_values` hook exists so a non-list `values:`
  produces the "write entries with YAML dashes" message rather than a generic
  Pydantic type error. Omitting the dash is the likeliest authoring slip.
- YAML turns an unquoted ISO date into a `datetime.date`, so `RangeBounds`
  bounds accept `dt.date` alongside `str` and numbers.
