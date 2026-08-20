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
from shelves.validation import _did_you_mean, detect_kind

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


def list_models(ctx: MCPContext) -> list[dict]:
    """List available semantic models in the models directory.

    One entry per `*.yaml` (excluding parameters files): a valid model yields
    ``{model, label, source_type}``; a file that fails to parse is surfaced as
    ``{model, error}`` so an agent can see a broken model exists rather than
    silently missing it.
    """
    out: list[dict] = []
    for stem in _model_stems(ctx.models_dir):
        try:
            model = load_model(stem, models_dir=ctx.models_dir)
        except (ValueError, FileNotFoundError) as e:
            out.append({"model": stem, "error": str(e).splitlines()[0]})
            continue
        out.append(
            {
                "model": model.model,
                "label": model.label,
                "source_type": _source_type(model),
            }
        )
    return out


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
    block = load_parameters(models_dir=ctx.models_dir)
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
        except yaml.YAMLError:
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
    return {"charts": charts, "dashboards": dashboards}
