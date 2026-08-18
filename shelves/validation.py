"""
Unified Error Renderer (SHE-54)

Validation errors are a product surface for coding agents: every error must be
paste-able into an LLM context and acted on in one turn. `validate_chart_yaml`
is the single renderer behind three consumers — the `shelves-lint` CLI, the MCP
`validate_spec` tool (SHE-56), and (later) Studio inline diagnostics. Do not
fork the format.

Contract (see `docs/foundational/MCP Specification.md` §4 and
`LLM Writability Specification.md` §4.1):

* One structured error per problem, each carrying `path`, `line`, `col`, a
  stable `code`, a `source`, a plain-language `message`, and — whenever they
  help — `did_you_mean`, `valid_options`, and a one-sentence `fix_hint`.
* All errors in one response — collect, never fail-fast.
* Semantic-model errors (unknown field, wrong grain) rank ABOVE structural
  schema errors — they are the likelier LLM mistake.
* On success, echo the spec back in canonical `normalized` form so agents learn
  the canon.

Voice: direct and actionable, never blaming the writer. "Unknown field 'revnue'
in model 'orders'." — not "ValidationError: value_error".
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError

from shelves.params.refs import INTERP_RE, WHOLE_REF_RE
from shelves.schema.chart_schema import HEX_COLOR_RE, ChartSpec
from shelves.schema.yaml_position import resolve_locs, yaml_loc_to_position

ErrorSource = Literal["yaml", "schema", "model"]


# ─── Structured error shape ───────────────────────────────────────


class ValidationErrorItem(BaseModel):
    """One structured, agent-grade validation error.

    Named `ValidationErrorItem` (not `ShelvesError`) to avoid colliding with
    the `shelves.errors.ShelvesError` exception base — this is data, not an
    exception. The MCP tool serializes these to JSON verbatim.
    """

    path: str  # dotted display path, e.g. "rows[0].measure"
    loc: list[str | int]  # raw pydantic loc (empty for yaml/model errors)
    line: int | None
    col: int | None
    code: str  # stable machine code (see module docstring / plan)
    source: ErrorSource
    message: str  # plain language: names the value and the place
    did_you_mean: str | None = None
    valid_options: list[str] | None = None
    fix_hint: str | None = None


class ValidationResult(BaseModel):
    """The result of validating one spec.

    `errors` is empty on success. `normalized` is the canonical YAML echo, set
    only when valid. `model_checked` is False when no models dir was available,
    so a consumer knows semantic checks were skipped rather than passed.
    """

    valid: bool
    kind: Literal["chart", "dashboard"] | None
    errors: list[ValidationErrorItem]
    normalized: str | None = None
    model_checked: bool = False


# ─── Friendly-message table (shared with the studio route) ─────────

# Kept here so the studio compile route and the CLI render Pydantic errors
# identically — one table, not two. Values are either a replacement string or a
# callable that rewrites the raw Pydantic message. `friendly_message()` is the
# shared entry point (the studio /compile route imports it).
_FRIENDLY_MESSAGES: dict[str, str | Callable[[str], str]] = {
    "missing": "Required field",
    "extra_forbidden": "Unknown field",
    "string_type": "Expected a text value",
    "int_type": "Expected a whole number",
    "float_type": "Expected a number",
    "bool_type": "Expected true or false",
    "model_type": "Expected a name or an object with properties",
    "less_than_equal": lambda msg: msg.replace("Input should be l", "Value should be l"),
    "greater_than_equal": lambda msg: msg.replace("Input should be g", "Value should be g"),
}

_LITERAL_RE = re.compile(r"^Input should be (.+)$")


def friendly_message(err_type: str, raw_msg: str) -> str:
    """Human-readable rewrite of a raw Pydantic message (surface-agnostic).

    Shared by the studio /compile route and the structured renderer so the two
    never drift. Falls back to the raw message when no rule applies.
    """
    entry = _FRIENDLY_MESSAGES.get(err_type)
    if entry is not None:
        return entry(raw_msg) if callable(entry) else entry

    if err_type == "literal_error":
        m = _LITERAL_RE.match(raw_msg)
        if m:
            values = m.group(1).replace("'", "").replace(" or ", ", ")
            return f"Invalid value. Expected: {values}"

    return raw_msg


# Pydantic error types that are just union noise: when a value fails a
# `str | SomeModel` union, the model arm emits one of these alongside the
# meaningful error. We drop them when a more specific sibling shares the path.
_UNION_NOISE_TYPES = frozenset({"model_type", "model_attributes_type", "dict_type"})

# The *scalar* arm of a `str | SomeModel` union emits one of these when the
# value is actually an object (e.g. `color: {field: .., tpe: ..}` fails the
# `str` arm with `string_type`). Unlike the model-noise types these can also be
# genuine standalone errors (`cols: 123`), so we only drop them when a real
# error lives at the same path or a descendant of it.
_SCALAR_NOISE_TYPES = frozenset({"string_type", "int_type", "float_type", "bool_type"})


def _parse_expected(expected: str) -> list[str]:
    """Parse a Pydantic literal `ctx['expected']` into an options list.

    "'bar', 'line' or 'geoshape'" -> ["bar", "line", "geoshape"]
    """
    parts = expected.replace(" or ", ", ").split(", ")
    return [p.strip().strip("'\"") for p in parts if p.strip()]


def _did_you_mean(value: str, options: Sequence[str]) -> str | None:
    """Closest single near-match to `value` among `options`, or None."""
    matches = difflib.get_close_matches(value, list(options), n=1, cutoff=0.6)
    return matches[0] or None if matches else None


def _path_str(display_loc: Sequence[str | int]) -> str:
    """Render a cleaned loc as a dotted/indexed path: ['rows', 0, 'measure'] → 'rows[0].measure'."""
    out = ""
    for seg in display_loc:
        if isinstance(seg, int):
            out += f"[{seg}]"
        elif out:
            out += f".{seg}"
        else:
            out = str(seg)
    return out


# ─── Pydantic → structured conversion ─────────────────────────────


def _convert_pydantic_error(err: Mapping[str, Any], info: dict) -> ValidationErrorItem:
    """Turn one `ValidationError.errors()` entry (+ position) into a ValidationErrorItem."""
    err_type = err["type"]
    display_loc = info["display_loc"]
    path = _path_str(display_loc)
    pos = info["position"]
    line = pos[0] if pos else None
    col = pos[1] if pos else None

    did_you_mean: str | None = None
    valid_options: list[str] | None = None
    fix_hint: str | None = None

    if err_type == "literal_error":
        code = "invalid_enum"
        expected = err.get("ctx", {}).get("expected", "")
        valid_options = _parse_expected(expected) if expected else None
        bad = err.get("input")
        if valid_options and isinstance(bad, str):
            did_you_mean = _did_you_mean(bad, valid_options)
        message = f"{bad!r} is not a valid value for '{path}'."
        fix_hint = f"Set '{path}' to one of valid_options."
    elif err_type == "extra_forbidden":
        code = "unknown_key"
        last = display_loc[-1] if display_loc else path
        if isinstance(last, str):
            did_you_mean = _did_you_mean(last, list(ChartSpec.model_fields.keys()))
        message = f"Unknown key '{path}'."
        fix_hint = f"Remove '{path}'" + (
            f" or replace it with '{did_you_mean}'." if did_you_mean else "."
        )
    elif err_type == "missing":
        code = "missing"
        message = f"Missing required field '{path}'."
        fix_hint = f"Add the '{path}' key."
    else:
        code = err_type
        message = friendly_message(err_type, err["msg"])

    return ValidationErrorItem(
        path=path,
        loc=list(err["loc"]),
        line=line,
        col=col,
        code=code,
        source="schema",
        message=message,
        did_you_mean=did_you_mean,
        valid_options=valid_options,
        fix_hint=fix_hint,
    )


def _dedupe_union_noise(errors: list[ValidationErrorItem]) -> list[ValidationErrorItem]:
    """Drop union-noise errors (e.g. `model_type`) when a real error shares the path.

    A `str | MarkObject` field that gets a bad literal emits BOTH a
    `literal_error` and a `model_type` at the same display path; a
    `str | ColorFieldMapping` field with a nested typo emits a `string_type`
    (failed str arm) at the field path alongside the real `unknown_key` at the
    nested key. Agents only need the informative one; keeping the noise would
    also break the "N mistakes → N errors" contract.
    """
    signal_paths = {
        e.path
        for e in errors
        if e.code not in _UNION_NOISE_TYPES and e.code not in _SCALAR_NOISE_TYPES
    }

    def _has_signal_at_or_below(path: str) -> bool:
        return any(
            s == path or s.startswith(f"{path}.") or s.startswith(f"{path}[") for s in signal_paths
        )

    kept: list[ValidationErrorItem] = []
    for e in errors:
        if e.code in _UNION_NOISE_TYPES and e.path in signal_paths:
            continue
        if e.code in _SCALAR_NOISE_TYPES and _has_signal_at_or_below(e.path):
            continue
        kept.append(e)
    return kept


# ─── Semantic-model checks ────────────────────────────────────────


def _is_param_ref(value: str) -> bool:
    """True for a `$name` / `${name}` parameter reference.

    Parameters are substituted before the spec is parsed (`parse_chart` →
    `substitute_parameters`), but `validate_chart_yaml` works on the RAW dict —
    so an unresolved `$revenue` would otherwise be checked as a field name and
    wrongly flagged `unknown_field`. We cannot resolve references here (no
    ParameterSet), so we skip them in the semantic pass instead.
    """
    return bool(WHOLE_REF_RE.match(value) or INTERP_RE.search(value))


def _model_field_refs(raw: dict) -> list[tuple[str, tuple[str | int, ...]]]:
    """Collect (field_ref, loc) pairs from the raw dict for every field-bearing slot.

    Walks the RAW mapping (not a parsed spec) so positions are available and so
    the pass still runs when schema validation failed. Only pulls values that
    are genuine field references — hex colors, numeric sizes, and unresolved
    parameter references are skipped.
    """
    pairs: list[tuple[str, tuple[str | int, ...]]] = []

    def _add(value: object, loc: tuple[str | int, ...]) -> None:
        if isinstance(value, str) and value and not _is_param_ref(value):
            pairs.append((value, loc))

    def _shelf(key: str) -> None:
        shelf = raw.get(key)
        if isinstance(shelf, str):
            _add(shelf, (key,))
        elif isinstance(shelf, list):
            for i, entry in enumerate(shelf):
                if not isinstance(entry, dict):
                    continue
                _add(entry.get("measure"), (key, i, "measure"))
                layers = entry.get("layer")
                if isinstance(layers, list):
                    for j, layer in enumerate(layers):
                        if isinstance(layer, dict):
                            _add(layer.get("measure"), (key, i, "layer", j, "measure"))

    def _color(value: object, loc: tuple[str | int, ...]) -> None:
        if isinstance(value, str) and not HEX_COLOR_RE.match(value):
            _add(value, loc)
        elif isinstance(value, dict):
            _add(value.get("field"), (*loc, "field"))

    _shelf("cols")
    _shelf("rows")
    _color(raw.get("color"), ("color",))
    _add(raw.get("detail"), ("detail",))
    if isinstance(raw.get("size"), str):
        _add(raw.get("size"), ("size",))

    tooltip = raw.get("tooltip")
    if isinstance(tooltip, list):
        for i, t in enumerate(tooltip):
            if isinstance(t, str):
                _add(t, ("tooltip", i))
            elif isinstance(t, dict):
                _add(t.get("field"), ("tooltip", i, "field"))

    filters = raw.get("filters")
    if isinstance(filters, list):
        for i, f in enumerate(filters):
            if isinstance(f, dict):
                _add(f.get("field"), ("filters", i, "field"))

    sort = raw.get("sort")
    if isinstance(sort, dict) and "field" in sort:
        _add(sort.get("field"), ("sort", "field"))

    facet = raw.get("facet")
    if isinstance(facet, dict):
        for fkey in ("row", "column", "field"):
            if fkey in facet:
                _add(facet.get(fkey), ("facet", fkey))

    label = raw.get("label")
    if isinstance(label, dict) and "field" in label:
        _add(label.get("field"), ("label", "field"))

    kpi = raw.get("kpi")
    if isinstance(kpi, dict):
        _add(kpi.get("value"), ("kpi", "value"))
        comparison = kpi.get("comparison")
        if isinstance(comparison, dict):
            _add(comparison.get("field"), ("kpi", "comparison", "field"))

    return pairs


def _semantic_errors(
    raw: dict,
    models_dir: Path | str | None,
    yaml_text: str,
) -> list[ValidationErrorItem]:
    """Check every field reference against the loaded semantic model.

    Returns one error per bad reference. Loads the model named by `raw['data']`;
    an unknown model is itself a (single) `unknown_model` error.
    """
    from shelves.models.loader import load_model
    from shelves.models.resolver import ModelResolver

    data_name = raw.get("data")
    if not isinstance(data_name, str) or not data_name:
        return []  # no model to check against

    dir_path = Path(models_dir) if models_dir is not None else None
    try:
        model = load_model(data_name, models_dir=models_dir)
    except FileNotFoundError:
        options = (
            sorted(p.stem for p in dir_path.glob("*.yaml"))
            if dir_path and dir_path.exists()
            else []
        )
        pos = yaml_loc_to_position(yaml_text, ("data",), position="value")
        return [
            ValidationErrorItem(
                path="data",
                loc=["data"],
                line=pos[0] if pos else None,
                col=pos[1] if pos else None,
                code="unknown_model",
                source="model",
                message=f"Unknown model '{data_name}'.",
                did_you_mean=_did_you_mean(data_name, options),
                valid_options=options or None,
                fix_hint="Set 'data' to a model that exists in your models directory.",
            )
        ]
    except ValueError:
        return []  # malformed model manifest — a models-layer concern, not this spec's

    resolver = ModelResolver(model)
    measures = sorted(model.measures.keys())
    dimensions = sorted(model.dimensions.keys())
    field_options = measures + dimensions

    errors: list[ValidationErrorItem] = []
    for ref, loc in _model_field_refs(raw):
        try:
            resolver._lookup(ref)
        except ValueError as exc:
            pos = yaml_loc_to_position(yaml_text, loc, position="value")
            line = pos[0] if pos else None
            col = pos[1] if pos else None
            path = _path_str(loc)
            base = ref.split(".", 1)[0]
            if "not found" in str(exc):
                errors.append(
                    ValidationErrorItem(
                        path=path,
                        loc=list(loc),
                        line=line,
                        col=col,
                        code="unknown_field",
                        source="model",
                        message=f"Unknown field '{base}' in model '{model.model}'.",
                        did_you_mean=_did_you_mean(base, field_options),
                        valid_options=field_options,
                        fix_hint=(
                            f"Replace '{base}' with one of valid_options (see did_you_mean)."
                        ),
                    )
                )
            else:
                errors.append(
                    ValidationErrorItem(
                        path=path,
                        loc=list(loc),
                        line=line,
                        col=col,
                        code="invalid_grain",
                        source="model",
                        message=str(exc),
                        fix_hint="Use a temporal field for grain suffixes, or drop the suffix.",
                    )
                )
    return errors


# ─── Dashboard semantic checks ────────────────────────────────────


def _dashboard_sheet_refs(
    raw: object, loc: tuple[str | int, ...] = ()
) -> list[tuple[str, tuple[str | int, ...]]]:
    """Collect (chart_path, loc) for every sheet reference in a dashboard.

    A sheet leaf is written as the value of a ``sheet:`` key (both the inline
    leaf form and named components in the ``components`` block), so walking the
    RAW dict for `sheet:` string values finds every referenced chart file with
    its YAML position. Bare-string component *references* are names, not paths,
    and are correctly ignored.
    """
    pairs: list[tuple[str, tuple[str | int, ...]]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key == "sheet" and isinstance(value, str) and value:
                pairs.append((value, (*loc, "sheet")))
            pairs.extend(_dashboard_sheet_refs(value, (*loc, key)))
    elif isinstance(raw, list):
        for i, item in enumerate(raw):
            pairs.extend(_dashboard_sheet_refs(item, (*loc, i)))
    return pairs


def _dashboard_sheet_errors(
    raw: dict,
    project_dir: Path | str | None,
    yaml_text: str,
) -> list[ValidationErrorItem]:
    """Report every referenced sheet (chart file) that does not exist on disk.

    Paths resolve relative to `project_dir` (the dashboard file's directory) —
    the same base `compose_dashboard` uses as `charts_dir`.
    """
    if project_dir is None:
        return []
    base = Path(project_dir)
    errors: list[ValidationErrorItem] = []
    for link, loc in _dashboard_sheet_refs(raw):
        if (base / link).exists():
            continue
        pos = yaml_loc_to_position(yaml_text, loc, position="value")
        errors.append(
            ValidationErrorItem(
                path=_path_str(loc),
                loc=list(loc),
                line=pos[0] if pos else None,
                col=pos[1] if pos else None,
                code="missing_sheet",
                source="model",
                message=f"Referenced sheet '{link}' was not found.",
                fix_hint=(
                    "Create the chart file, or fix the link path — it resolves "
                    "relative to the dashboard file's directory."
                ),
            )
        )
    return errors


# ─── Kind detection ───────────────────────────────────────────────


def detect_kind(raw: dict) -> Literal["chart", "dashboard"] | None:
    """Classify a parsed mapping as a chart or dashboard by its root key.

    Confirmed against layout_schema.py: DashboardSpec requires a top-level
    `dashboard:` key; ChartSpec uses `sheet:`. Anything else is None (treated
    as a chart so schema errors speak for themselves).
    """
    if "sheet" in raw:
        return "chart"
    if "dashboard" in raw:
        return "dashboard"
    return None


# ─── Public entry points ──────────────────────────────────────────


def _empty(code: str, message: str, *, fix_hint: str | None = None) -> ValidationResult:
    return ValidationResult(
        valid=False,
        kind=None,
        errors=[
            ValidationErrorItem(
                path="",
                loc=[],
                line=None,
                col=None,
                code=code,
                source="yaml",
                message=message,
                fix_hint=fix_hint,
            )
        ],
        model_checked=False,
    )


def _prelude(yaml_text: str) -> tuple[dict | None, ValidationResult | None]:
    """Shared front of the pipeline: empty / syntax / not-a-mapping guards.

    Returns (raw_dict, None) when parsing succeeded, or (None, early_result)
    when one of the guards fired.
    """
    if not yaml_text.strip():
        return None, _empty(
            "empty_input",
            "The file is empty — a chart spec needs at least sheet, data, and rows/cols.",
        )

    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        line = None
        col = None
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            line = mark.line + 1
            col = mark.column + 1
        problem = getattr(exc, "problem", None) or str(exc)
        return None, ValidationResult(
            valid=False,
            kind=None,
            errors=[
                ValidationErrorItem(
                    path="",
                    loc=[],
                    line=line,
                    col=col,
                    code="yaml_syntax",
                    source="yaml",
                    message=str(problem),
                    fix_hint="Fix the YAML syntax at the reported line.",
                )
            ],
            model_checked=False,
        )

    if raw is None or not isinstance(raw, dict):
        return None, _empty(
            "not_a_mapping",
            "A spec must be a mapping of keys to values, not a list or scalar.",
            fix_hint="Start the file with top-level keys like `sheet:` and `data:`.",
        )

    return raw, None


def validate_chart_yaml(
    yaml_text: str,
    *,
    models_dir: Path | str | None = None,
) -> ValidationResult:
    """Validate a chart YAML spec, returning every error in one structured response.

    Runs YAML-syntax, schema (Pydantic), then semantic-model checks. Semantic
    errors are ranked first. On success `normalized` echoes the spec in
    canonical form (shorthands expanded, None fields dropped).
    """
    raw, early = _prelude(yaml_text)
    if early is not None:
        return early
    assert raw is not None

    # Schema (Pydantic) pass.
    spec: ChartSpec | None = None
    schema_errors: list[ValidationErrorItem] = []
    try:
        spec = ChartSpec.model_validate(raw)
    except ValidationError as exc:
        raw_errors = exc.errors()
        resolved = resolve_locs(yaml_text, [tuple(e["loc"]) for e in raw_errors])
        schema_errors = [
            _convert_pydantic_error(e, info) for e, info in zip(raw_errors, resolved, strict=True)
        ]
        schema_errors = _dedupe_union_noise(schema_errors)

    # Semantic-model pass (best-effort; runs whether or not schema passed).
    model_checked = models_dir is not None and "data" in raw
    model_errors: list[ValidationErrorItem] = []
    if model_checked:
        model_errors = _semantic_errors(raw, models_dir, yaml_text)

    errors = model_errors + schema_errors  # model errors rank first
    valid = not errors

    normalized: str | None = None
    if valid and spec is not None:
        normalized = yaml.safe_dump(
            spec.model_dump(exclude_none=True, mode="json"),
            sort_keys=False,
            allow_unicode=True,
        )

    return ValidationResult(
        valid=valid,
        kind="chart",
        errors=errors,
        normalized=normalized,
        model_checked=model_checked,
    )


def validate_dashboard_yaml(
    yaml_text: str,
    *,
    models_dir: Path | str | None = None,
    project_dir: Path | str | None = None,
) -> ValidationResult:
    """Validate a dashboard YAML spec.

    Schema pass against DashboardSpec, plus a v1 semantic pass (when
    `project_dir` is given): every referenced sheet (chart file) must exist on
    disk relative to `project_dir`. `models_dir` is accepted for signature
    parity with `validate_chart_yaml` and reserved for future per-sheet field
    validation — it is not consulted yet. Richer layout checks are out of scope
    for SHE-54.
    """
    from shelves.schema.layout_schema import DashboardSpec

    raw, early = _prelude(yaml_text)
    if early is not None:
        return early
    assert raw is not None

    # Semantic pass: referenced sheets must exist on disk (best-effort; runs
    # whether or not the schema pass produced errors). Sheet errors rank first.
    # Collect refs BEFORE model_validate — DashboardSpec's before-validator
    # mutates `raw` in place, which would erase the original `sheet:` keys.
    sheet_checked = project_dir is not None
    sheet_errors = _dashboard_sheet_errors(raw, project_dir, yaml_text) if sheet_checked else []

    spec = None
    schema_errors: list[ValidationErrorItem] = []
    try:
        spec = DashboardSpec.model_validate(raw)
    except ValidationError as exc:
        raw_errors = exc.errors()
        resolved = resolve_locs(yaml_text, [tuple(e["loc"]) for e in raw_errors])
        schema_errors = [
            _convert_pydantic_error(e, info) for e, info in zip(raw_errors, resolved, strict=True)
        ]
        schema_errors = _dedupe_union_noise(schema_errors)

    errors = sheet_errors + schema_errors
    normalized: str | None = None
    if not errors and spec is not None:
        normalized = yaml.safe_dump(
            spec.model_dump(exclude_none=True, mode="json"),
            sort_keys=False,
            allow_unicode=True,
        )

    return ValidationResult(
        valid=not errors,
        kind="dashboard",
        errors=errors,
        normalized=normalized,
        model_checked=sheet_checked,
    )
