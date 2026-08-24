"""
MCP discovery-tool implementations (SHE-55).

Pure functions — no MCP protocol types in their signatures — so they are
trivially unit-testable and so `server.py` is a thin registration layer. Every
function returns a JSON-serializable dict (or list). Errors are RETURNED as
``{"error": {"code", "message", "did_you_mean"?, "valid_options"?, "fix_hint"?}}``
using the field vocabulary SHE-54 shipped (`shelves.validation.ValidationErrorItem`),
never raised across the protocol boundary.

Governing principle (MCP Specification §1): thin wrapper, no new logic. Each
tool adapts an existing public API — the model loader/resolver, the semantic-
layer domain resolver (`shelves.data.domains.resolve_field_domain`), and the
parameters loader. No SQL and no per-backend branching live here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from shelves.data.domains import LiteralParamType, resolve_field_domain
from shelves.data.errors import ParameterDomainError
from shelves.models.loader import load_model
from shelves.models.resolver import ModelResolver
from shelves.models.schema import DataModel
from shelves.params.loader import load_parameters
from shelves.params.schema import FieldRef
from shelves.schema.chart_schema import DSL_VERSION
from shelves.validation import (
    _did_you_mean,
    detect_kind,
    validate_chart_yaml,
    validate_dashboard_yaml,
)

# Directory / path parts never scanned for models or specs.
_SKIP_PARTS = {".venv", ".git", "output", "node_modules", "__pycache__"}
# Files in the models dir that are not models.
_NON_MODEL_FILES = {"parameters.yaml", "parameters.yml"}


@dataclass(frozen=True)
class MCPContext:
    """Where the server resolves models, data, and specs from.

    `models_dir` mirrors the CLIs' `--models-dir`; `project_dir` is the data
    base dir (relative source paths resolve against it) and the root
    `list_specs` inventories.
    """

    project_dir: Path
    models_dir: Path

    @classmethod
    def create(
        cls,
        project_dir: Path | str | None = None,
        models_dir: Path | str | None = None,
    ) -> MCPContext:
        root = Path(project_dir).resolve() if project_dir else Path.cwd()
        mdir = Path(models_dir).resolve() if models_dir else root / "models"
        return cls(project_dir=root, models_dir=mdir)


# ─── error helper ─────────────────────────────────────────────────


def _error(
    code: str,
    message: str,
    *,
    did_you_mean: str | None = None,
    valid_options: list[str] | None = None,
    fix_hint: str | None = None,
) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if did_you_mean is not None:
        err["did_you_mean"] = did_you_mean
    if valid_options is not None:
        err["valid_options"] = valid_options
    if fix_hint is not None:
        err["fix_hint"] = fix_hint
    return {"error": err}


def _first_pydantic_error(exc: Any, fallback: str) -> str:
    """First validation error as ``loc: msg`` — keep ``loc`` so a structural
    error points at the offending field instead of a bare, unanchored message."""
    errors = exc.errors()
    if not errors:
        return fallback
    first = errors[0]
    loc = ".".join(str(p) for p in first.get("loc", ()))
    msg = first.get("msg", fallback)
    return f"{loc}: {msg}" if loc else msg


def _iso(value: Any) -> Any:
    """ISO-format dates/datetimes; pass everything else through unchanged."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _source_type(model: DataModel) -> str | None:
    return model.source.type if model.source is not None else None


def _model_stems(models_dir: Path) -> list[str]:
    """Sorted stems of every *.yaml in `models_dir` that could be a model."""
    if not models_dir.is_dir():
        return []
    stems = {p.stem for p in models_dir.glob("*.yaml") if p.name not in _NON_MODEL_FILES}
    return sorted(stems)


# ─── list_models ──────────────────────────────────────────────────


def list_models(ctx: MCPContext) -> dict:
    """List available semantic models in the models directory.

    One entry per `*.yaml` (excluding parameters files) under ``models``: a valid
    model yields ``{model, label, source_type}``; a file that fails to parse is
    surfaced as ``{model, error}`` so an agent can see a broken model exists
    rather than silently missing it. The result carries the DSL schema version.
    """
    models: list[dict] = []
    for stem in _model_stems(ctx.models_dir):
        try:
            model = load_model(stem, models_dir=ctx.models_dir)
        except (ValueError, FileNotFoundError) as e:
            models.append({"model": stem, "error": str(e).splitlines()[0]})
            continue
        models.append(
            {
                "model": model.model,
                "label": model.label,
                "source_type": _source_type(model),
            }
        )
    return {"models": models, "dsl_version": DSL_VERSION}


# ─── get_model ────────────────────────────────────────────────────


def _serialize_measure(name: str, defn: Any) -> dict:
    return {
        "name": name,
        "label": defn.label,
        "format": defn.format,
        "aggregation": defn.aggregation,
        "description": defn.description,
        "calculated": defn.calculation is not None,
    }


def _serialize_dimension(name: str, defn: Any) -> dict:
    base = {
        "name": name,
        "label": defn.label,
        "type": defn.type,
        "description": defn.description,
    }
    if defn.type == "temporal":
        base["grains"] = list(defn.grains)
        base["default_grain"] = defn.defaultGrain
        base["usage"] = (
            f"{name} (default grain: {defn.defaultGrain}); use {name}.<grain> for an explicit grain"
        )
    return base


def get_model(ctx: MCPContext, model: str) -> dict:
    """The metric menu for one model — call this first.

    Every measure (with format, aggregation, and a `calculated` flag) and
    dimension (with type; temporal dimensions add grains + default_grain +
    a usage hint). Reports the DSL schema version.
    """
    try:
        data_model = load_model(model, models_dir=ctx.models_dir)
    except FileNotFoundError:
        options = _model_stems(ctx.models_dir)
        return _error(
            "unknown_model",
            f"Unknown model {model!r}.",
            did_you_mean=_did_you_mean(model, options),
            valid_options=options,
        )
    except ValueError as e:
        return _error("invalid_model", str(e).splitlines()[0])

    return {
        "model": data_model.model,
        "label": data_model.label,
        "description": data_model.description,
        "source_type": _source_type(data_model),
        "dsl_version": DSL_VERSION,
        "measures": [_serialize_measure(n, d) for n, d in data_model.measures.items()],
        "dimensions": [_serialize_dimension(n, d) for n, d in data_model.dimensions.items()],
    }


# ─── sample_field_values ──────────────────────────────────────────

# Vega-Lite type → parameter domain type. `resolve_field_domain` returns a
# `values` Domain for "string" and a `bounds` Domain for "date"/"number".
_PARAM_TYPE_BY_VTYPE: dict[str, LiteralParamType] = {
    "temporal": "date",
    "quantitative": "number",
    "nominal": "string",
    "ordinal": "string",
}


def sample_field_values(ctx: MCPContext, model: str, field: str, limit: int = 20) -> dict:
    """Semantic-layer domain of a dimension.

    Nominal/ordinal fields return distinct `values` (for writing `in`/`eq`
    filters); temporal/numeric fields return `(min, max)` bounds (for `between`
    filters). Goes through `resolve_field_domain` — never raw SQL. `limit`
    applies to `values` only and is ignored for bounds.
    """
    try:
        data_model = load_model(model, models_dir=ctx.models_dir)
    except FileNotFoundError:
        options = _model_stems(ctx.models_dir)
        return _error(
            "unknown_model",
            f"Unknown model {model!r}.",
            did_you_mean=_did_you_mean(model, options),
            valid_options=options,
        )
    except ValueError as e:
        # A model file that exists but is malformed — surface it as a structured
        # error, never raised across the protocol boundary (spec §1 principle 3).
        return _error("invalid_model", str(e).splitlines()[0])

    resolver = ModelResolver(data_model)
    dimension_names = list(data_model.dimensions.keys())

    try:
        vtype = resolver.resolve_type(field)
    except ValueError:
        return _error(
            "unknown_field",
            f"Unknown field {field!r} in model {model!r}.",
            did_you_mean=_did_you_mean(field, dimension_names),
            valid_options=dimension_names,
        )

    if resolver.is_measure(field):
        return _error(
            "not_a_dimension",
            f"{field!r} is a measure; sample_field_values is for dimensions.",
            valid_options=dimension_names,
        )

    param_type = _PARAM_TYPE_BY_VTYPE.get(vtype, "string")
    try:
        domain = resolve_field_domain(
            FieldRef(model=model, field=field),
            param_type,
            models_dir=ctx.models_dir,
            data_base_dir=ctx.project_dir,
        )
    except ParameterDomainError as e:
        return _error("domain_error", str(e).splitlines()[0])

    if domain.kind == "values":
        values = list(domain.values or [])
        truncated = domain.truncated or len(values) > limit
        return {
            "field": field,
            "kind": "values",
            "values": [_iso(v) for v in values[:limit]],
            "truncated": truncated,
            "dsl_version": DSL_VERSION,
        }

    return {
        "field": field,
        "kind": "bounds",
        "min": _iso(domain.min),
        "max": _iso(domain.max),
        "truncated": domain.truncated,
        "dsl_version": DSL_VERSION,
    }


# ─── list_parameters ──────────────────────────────────────────────


def list_parameters(ctx: MCPContext) -> dict:
    """Declared runtime parameters (the parameters analog of get_model).

    Each: name, type, label, default, and `has_field_domain` — True when the
    parameter's values come from a model field, signalling the agent can call
    `sample_field_values` on it. No data is fetched here.
    """
    try:
        block = load_parameters(models_dir=ctx.models_dir)
    except (ValueError, FileNotFoundError) as e:
        # A malformed parameters.yaml is an agent-correctable error, not a
        # protocol crash (spec §1 principle 3) — mirror list_models' handling.
        return _error("invalid_parameters", str(e).splitlines()[0])
    params = []
    for name, param in block.items():
        entries = param.values or []
        has_field_domain = (
            len(entries) == 1 and isinstance(entries[0], FieldRef) and entries[0].field is not None
        )
        params.append(
            {
                "name": name,
                "type": param.type,
                "label": param.label,
                "default": _iso(param.default),
                "has_field_domain": has_field_domain,
            }
        )
    return {"parameters": params, "dsl_version": DSL_VERSION}


# ─── list_specs ───────────────────────────────────────────────────


def _classify(raw: Any) -> str | None:
    """chart / dashboard / None for a parsed YAML mapping."""
    if not isinstance(raw, dict):
        return None
    return detect_kind(raw)


def list_specs(ctx: MCPContext, kind: str | None = None) -> dict:
    """Inventory of chart and dashboard YAMLs in the project.

    So an agent extends existing specs rather than duplicating them. Charts
    carry their `sheet` title; dashboards their `name`. Model and parameter
    YAMLs are excluded. `kind` ("chart"/"dashboard") narrows the result.
    """
    charts: list[dict] = []
    dashboards: list[dict] = []

    for path in sorted(ctx.project_dir.rglob("*.yaml")):
        rel = path.relative_to(ctx.project_dir)
        if any(part in _SKIP_PARTS or part.startswith(".") for part in rel.parts):
            continue
        try:
            raw = yaml.safe_load(path.read_text())
        except (yaml.YAMLError, OSError, UnicodeDecodeError):
            # An unreadable / non-UTF-8 / malformed *.yaml is skipped, not fatal —
            # a single bad file must never abort the whole inventory (spec §1
            # principle 3: no raise across the protocol boundary).
            continue
        spec_kind = _classify(raw)
        rel_str = str(rel)
        if spec_kind == "chart":
            charts.append({"path": rel_str, "sheet": raw.get("sheet")})
        elif spec_kind == "dashboard":
            dashboards.append({"path": rel_str, "name": raw.get("dashboard")})

    if kind == "chart":
        dashboards = []
    elif kind == "dashboard":
        charts = []
    return {"charts": charts, "dashboards": dashboards, "dsl_version": DSL_VERSION}


# ─── authoring tools (SHE-56) ─────────────────────────────────────

_LABEL_LIMITATION = "Data labels (label:) are browser-rendered and do not appear in PNG output."
_COMPOUND_LIMITATION = "Compound specs render at natural size, not container-fit."
_PARAMS_UNSUPPORTED = "Parameters land with the Parameter spec; render without params for now."
_CHART_FORMATS = {"png", "html"}


def _read_input(
    ctx: MCPContext, yaml_text: str | None, path: str | None
) -> tuple[str | None, dict | None]:
    """Resolve exactly one of `yaml_text` / `path` to spec text (text, error)."""
    if yaml_text is not None and path is not None:
        return None, _error("ambiguous_input", "Pass yaml_text or path, not both.")
    if yaml_text is None and path is None:
        return None, _error("missing_input", "Pass either yaml_text or path.")
    if yaml_text is not None:
        return yaml_text, None

    assert path is not None
    resolved = (ctx.project_dir / path).resolve()
    if not resolved.is_relative_to(ctx.project_dir):
        return None, _error(
            "outside_project", f"Path {path!r} resolves outside the project directory."
        )
    try:
        return resolved.read_text(), None
    except (OSError, UnicodeDecodeError) as e:
        return None, _error("read_error", str(e).splitlines()[0])


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "_" for c in text.strip()]
    slug = "".join(keep).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "chart"


def _content_hash(text: str) -> str:
    """Short stable digest of the spec text — disambiguates output filenames so
    two charts that share a `sheet` title don't overwrite each other's PNG."""
    import hashlib

    return hashlib.sha1(text.encode()).hexdigest()[:8]


def _resolve_theme(ctx: MCPContext, theme: str | None) -> tuple[Path | None, dict | None]:
    """Resolve a theme path like `path`: against `project_dir`, contained, existing.

    Returns (path, error). A bad or hostile theme value must come back as a
    structured error, never raise across the protocol boundary (spec §1).
    """
    if theme is None:
        return None, None
    resolved = (ctx.project_dir / theme).resolve()
    if not resolved.is_relative_to(ctx.project_dir):
        return None, _error(
            "outside_project", f"Theme path {theme!r} resolves outside the project directory."
        )
    if not resolved.is_file():
        return None, _error("theme_not_found", f"Theme file {theme!r} does not exist.")
    return resolved, None


def _detect_kind(text: str, kind: str | None) -> str:
    if kind is not None:
        return kind
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError:
        return "chart"
    detected = detect_kind(raw) if isinstance(raw, dict) else None
    return detected or "chart"


def validate_spec(
    ctx: MCPContext,
    yaml_text: str | None = None,
    path: str | None = None,
    kind: str | None = None,
) -> dict:
    """Validate chart or dashboard YAML against schema AND the semantic model.

    Returns every error at once — line/column, valid options, and did-you-mean
    suggestions — or, when valid, the normalized canonical spec. Kind is inferred
    from the root keys unless given. This is the SHE-54 renderer verbatim.
    """
    text, err = _read_input(ctx, yaml_text, path)
    if err is not None:
        return err
    assert text is not None

    if _detect_kind(text, kind) == "dashboard":
        result = validate_dashboard_yaml(
            text, models_dir=ctx.models_dir, project_dir=ctx.project_dir
        )
    else:
        result = validate_chart_yaml(text, models_dir=ctx.models_dir)
    return result.model_dump()


def compile_chart(
    ctx: MCPContext,
    yaml_text: str | None = None,
    path: str | None = None,
    theme: str | None = None,
) -> dict:
    """Compiled, theme-merged Vega-Lite for one chart (no data) — for inspection.

    Invalid specs return the validate_spec error payload instead of raising.
    """
    text, err = _read_input(ctx, yaml_text, path)
    if err is not None:
        return err
    assert text is not None

    theme_path, theme_err = _resolve_theme(ctx, theme)
    if theme_err is not None:
        return theme_err

    result = validate_chart_yaml(text, models_dir=ctx.models_dir)
    if not result.valid:
        return result.model_dump()

    from shelves.pipeline import compile_chart as _compile

    vl_spec, spec = _compile(text, models_dir=ctx.models_dir, theme_path=theme_path)
    return {"vega_lite": vl_spec, "sheet": spec.sheet, "dsl_version": DSL_VERSION}


def _has_label(spec: Any) -> bool:
    if spec.label:
        return True
    for shelf in (spec.rows, spec.cols):
        if isinstance(shelf, list):
            for entry in shelf:
                if entry.label:
                    return True
                if entry.layer and any(layer.label for layer in entry.layer):
                    return True
    return False


def _inline_data_error(ctx: MCPContext, spec: Any) -> dict | None:
    """Structured error for the two inline failures `resolve_model_data` hides.

    Only inline sources are checked here — file/cube sources fetch inside
    `resolve_model_data` and raise `ShelvesError`, which the caller catches. The
    spec has already validated against its model, so `load_model` succeeds.
    """
    import json

    model = load_model(spec.data, models_dir=ctx.models_dir)
    if not (model.source and model.source.type == "inline"):
        return None
    src = Path(model.source.path)
    if not src.is_absolute():
        src = ctx.project_dir / src
    if not src.exists():
        return _error(
            "data_unavailable",
            f"Inline data file not found: {model.source.path}",
            fix_hint="Point the model's inline source at an existing JSON file.",
        )
    try:
        json.loads(src.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return _error(
            "invalid_data", f"Inline data file is not valid JSON: {str(e).splitlines()[0]}"
        )
    return None


def _render_limitations(spec: Any, vl_spec: dict) -> list[str]:
    limitations: list[str] = []
    if _has_label(spec):
        limitations.append(_LABEL_LIMITATION)
    if any(k in vl_spec for k in ("vconcat", "hconcat", "repeat", "facet")):
        limitations.append(_COMPOUND_LIMITATION)
    return limitations


def render_chart(
    ctx: MCPContext,
    yaml_text: str | None = None,
    path: str | None = None,
    format: str = "png",
    params: dict | None = None,
) -> dict:
    """Render a chart to PNG (default — a multimodal agent can look at it) or HTML.

    PNG is headless (vl-convert): data labels and container-fit sizing for
    compound charts are browser-only and are reported in `limitations`. Use
    format="html" for full fidelity. Invalid specs return the validate_spec
    error payload; unresolvable data returns a `data_unavailable` error.
    """
    if params:
        return _error("not_supported_yet", _PARAMS_UNSUPPORTED)
    if format not in _CHART_FORMATS:
        return _error(
            "unsupported_format",
            f"Unknown format {format!r}.",
            valid_options=sorted(_CHART_FORMATS),
        )

    text, err = _read_input(ctx, yaml_text, path)
    if err is not None:
        return err
    assert text is not None

    result = validate_chart_yaml(text, models_dir=ctx.models_dir)
    if not result.valid:
        return result.model_dump()

    from shelves.errors import ShelvesError
    from shelves.pipeline import compile_chart as _compile
    from shelves.pipeline import resolve_model_data

    vl_spec, spec = _compile(text, models_dir=ctx.models_dir)

    # resolve_model_data hides two inline failures — a missing data file (silent
    # no-op → a successful but blank render) and malformed JSON (uncaught
    # JSONDecodeError). For the render surface a blank image is not a product;
    # surface both as structured errors instead.
    inline_err = _inline_data_error(ctx, spec)
    if inline_err is not None:
        return inline_err

    try:
        bound = resolve_model_data(
            vl_spec, spec, models_dir=ctx.models_dir, data_base_dir=ctx.project_dir
        )
    except ShelvesError as e:
        return _error(
            "data_unavailable",
            str(e).splitlines()[0],
            fix_hint="Set CUBE_API_URL/CUBE_API_TOKEN, or use a model with resolvable data.",
        )

    out_dir = ctx.project_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Include a content digest so two charts sharing a `sheet` title write to
    # distinct files instead of the later render clobbering the earlier one.
    slug = f"{_slug(spec.sheet)}_{_content_hash(text)}"

    if format == "html":
        from shelves.render.to_html import render_html

        out_path = out_dir / f"{slug}.html"
        out_path.write_text(render_html(bound, title=spec.sheet))
        return {"format": "html", "path": str(out_path), "dsl_version": DSL_VERSION}

    try:
        from shelves.render.to_png import render_png

        png, width, height = render_png(bound)
    except ModuleNotFoundError as e:
        if e.name == "vl_convert" or (e.name or "").startswith("vl_convert"):
            return _error(
                "vl_convert_missing",
                "PNG rendering needs the vl-convert-python package.",
                fix_hint='pip install "shelves-bi[mcp]"',
            )
        raise

    out_path = out_dir / f"{slug}.png"
    out_path.write_bytes(png)
    import base64

    return {
        "format": "png",
        "path": str(out_path),
        "png_base64": base64.b64encode(png).decode(),
        "width": width,
        "height": height,
        "limitations": _render_limitations(spec, bound),
        "dsl_version": DSL_VERSION,
    }


def render_dashboard(
    ctx: MCPContext,
    path: str,
    format: str = "html",
    params: dict | None = None,
) -> dict:
    """Render a dashboard (layout tree of sheets) to HTML via the compose pipeline.

    PNG is not supported — dashboard sizing is browser-computed; use HTML.
    """
    if params:
        return _error("not_supported_yet", _PARAMS_UNSUPPORTED)
    if format == "png":
        return _error(
            "unsupported_format",
            "Dashboard PNG needs a browser (layout sizing is browser-computed). "
            "Render format='html' instead.",
        )
    if format != "html":
        return _error(
            "unsupported_format",
            f"Unknown format {format!r}.",
            valid_options=["html"],
        )

    resolved = (ctx.project_dir / path).resolve()
    if not resolved.is_relative_to(ctx.project_dir):
        return _error("outside_project", f"Path {path!r} resolves outside the project directory.")

    from pydantic import ValidationError

    from shelves.compose.dashboard import compose_dashboard
    from shelves.diagnostics import capture_warnings
    from shelves.errors import ShelvesError

    # compose_dashboard reports per-sheet data/layout problems via warnings.warn
    # (the panel Studio surfaces); capture them so this surface returns them too
    # rather than discarding them into a clean-looking payload.
    compose_warnings: list[str] = []
    try:
        with capture_warnings(compose_warnings):
            html = compose_dashboard(
                resolved,
                chart_base_dir=ctx.project_dir,
                data_dir=ctx.project_dir,
                models_dir=ctx.models_dir,
            )
    except ShelvesError as e:
        return _error("data_unavailable", str(e).splitlines()[0])
    except FileNotFoundError as e:
        # A sheet's link path doesn't resolve to a file (compose fail-fast).
        return _error("chart_not_found", str(e).splitlines()[0])
    except ValidationError as e:
        return _error("invalid_dashboard", _first_pydantic_error(e, "invalid dashboard"))
    except (RuntimeError, ValueError) as e:
        # A sheet's chart YAML failed to compile (RuntimeError), or filter
        # validation failed (ValueError) — both documented compose raises.
        return _error("invalid_dashboard", str(e).splitlines()[0])

    out_dir = ctx.project_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{resolved.stem}.html"
    out_path.write_text(html)
    return {
        "format": "html",
        "path": str(out_path),
        "warnings": compose_warnings,
        "dsl_version": DSL_VERSION,
    }


def query_model(
    ctx: MCPContext,
    model: str,
    measures: list[str],
    dimensions: list[str] | None = None,
    filters: list[dict] | None = None,
    limit: int = 500,
) -> dict:
    """Aggregated rows for a measure/dimension selection through the semantic layer.

    Sanity-check data before or after charting. Read-only and SQL-free — routes
    through the same adapter a chart uses (file → DuckDB, cube → Cube.dev).
    """
    from pydantic import ValidationError

    from shelves.errors import ShelvesError
    from shelves.schema.chart_schema import ShelfFilter

    dimensions = dimensions or []
    if limit < 1:
        return _error(
            "invalid_limit",
            f"limit must be a positive integer, got {limit}.",
            fix_hint="Pass limit >= 1 (default 500).",
        )
    try:
        data_model = load_model(model, models_dir=ctx.models_dir)
    except FileNotFoundError:
        options = _model_stems(ctx.models_dir)
        return _error(
            "unknown_model",
            f"Unknown model {model!r}.",
            did_you_mean=_did_you_mean(model, options),
            valid_options=options,
        )
    except ValueError as e:
        return _error("invalid_model", str(e).splitlines()[0])

    resolver = ModelResolver(data_model)
    field_names = list(data_model.measures.keys()) + list(data_model.dimensions.keys())

    def _validate_field(name: str) -> dict | None:
        try:
            resolver.resolve_type(name)
        except ValueError:
            return _error(
                "unknown_field",
                f"Unknown field {name!r} in model {model!r}.",
                did_you_mean=_did_you_mean(name, field_names),
                valid_options=field_names,
            )
        return None

    for name in [*measures, *dimensions]:
        field_err = _validate_field(name)
        if field_err is not None:
            return field_err

    shelf_filters: list[ShelfFilter] | None = None
    if filters:
        try:
            shelf_filters = [ShelfFilter.model_validate(f) for f in filters]
        except ValidationError as e:
            return _error("invalid_filter", _first_pydantic_error(e, "invalid filter"))
        # A filter on a hallucinated field must be an agent-correctable error,
        # not the ValueError the resolver raises deep inside the adapter.
        for filt in shelf_filters:
            field_err = _validate_field(filt.field)
            if field_err is not None:
                return field_err

    from shelves.data.query import run_model_query

    try:
        rows = run_model_query(
            model,
            measures,
            dimensions,
            shelf_filters,
            models_dir=ctx.models_dir,
            data_base_dir=ctx.project_dir,
        )
    except (ShelvesError, KeyError) as e:
        return _error(
            "data_unavailable",
            str(e).splitlines()[0],
            fix_hint="query_model needs a file or cube source with resolvable data.",
        )

    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "dsl_version": DSL_VERSION,
    }
