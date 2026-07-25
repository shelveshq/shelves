"""
Parameter Domain Resolution

A parameter whose `values:` is a single `{model, field}` entry gets its domain
from the data — the distinct values of that field for a `string` parameter, its
min/max for `number` and `date`. SHE-89 parsed and stored the reference; this
module dereferences it, at compile time, through the data layer.

**The parity guarantee.** All three backends (inline JSON rows, DuckDB over a
flat file, Cube.dev) return RAW values. One normalizer here — `_normalize` —
turns them into the same Python objects. That is what makes "one parameter
declaration, three backends, identical domain" true by construction rather than
by coincidence. Never normalize inside an adapter.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from shelves.data.duckdb_adapter import DuckDBAdapter
from shelves.data.errors import ParameterDomainError
from shelves.data.sources import DataSourceAdapter, get_adapter
from shelves.errors import ShelvesError
from shelves.models.loader import load_model
from shelves.models.resolver import ModelResolver
from shelves.models.schema import DataModel, InlineSource
from shelves.params.schema import (
    FieldParameter,
    FieldRef,
    ParametersBlock,
    _fmt,
)

DomainKind = Literal["values", "bounds"]
LiteralParamType = Literal["string", "number", "date"]

MAX_DOMAIN_CARDINALITY = 500
"""Distinct values above which a domain must be listed explicitly (SHE-90)."""

_CARDINALITY_MESSAGE = (
    "field {source!r} has {limit} or more distinct values — too many for a "
    "parameter domain. List the values you want explicitly:\n"
    "  values:\n"
    "    - first\n"
    "    - second"
)

_EMPTY_MESSAGE = (
    "field {source!r} resolved to an empty domain — the data source returned no values."
)


@dataclass(frozen=True)
class Domain:
    """A parameter's value space, resolved from data at compile time.

    `kind == "values"` → `values` is a sorted, de-duplicated, null-free list and
    `min`/`max` are None.
    `kind == "bounds"` → `min`/`max` are set and `values` is None.

    `source` is a display string ("orders.region") used only in error messages.
    It is NOT the dotted field grammar — there is no `model.field` syntax in
    Shelves (see shelves/models/CLAUDE.md).
    """

    kind: DomainKind
    param_type: LiteralParamType
    source: str
    values: list[Any] | None = None
    min: Any = None
    max: Any = None


# ─── Normalizers — the single point of convergence ────────────────

_ISO_PREFIX_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


def _to_date(value: Any) -> dt.date:
    """Coerce a backend temporal value to a datetime.date.

    Handles every shape the three backends produce:
      datetime.datetime(2024,1,1,0,0)  → date(2024,1,1)
      datetime.date(2024,1,1)          → date(2024,1,1)
      "2024-01-01"                     → date(2024,1,1)
      "2024-01-01T00:00:00.000"        → date(2024,1,1)   (Cube)
      "2024-01-01T00:00:00"            → date(2024,1,1)   (DuckDB, serialized)
      "2024-01"                        → date(2024,1,1)
      "2024"                           → date(2024,1,1)

    `datetime.date.fromisoformat` rejects the last two, so the leading-ISO regex
    does the parsing and missing components default to 01.
    """
    # datetime is a subclass of date — check it FIRST or the time component
    # silently survives.
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value

    match = _ISO_PREFIX_RE.match(str(value))
    if match is None:
        raise ValueError(f"{value!r} is not a recognizable date")
    return dt.date(int(match[1]), int(match[2] or 1), int(match[3] or 1))


def _truncate(value: Any, grain: str | None) -> dt.date:
    """Truncate a date to the start of its grain.

    The inline backend's stand-in for DuckDB's DATE_TRUNC and Cube's
    `timeDimensions[].granularity`. Weeks start MONDAY, matching both.
    """
    date = _to_date(value)

    if grain is None or grain == "day":
        return date
    if grain == "week":
        return date - dt.timedelta(days=date.weekday())
    if grain == "month":
        return date.replace(day=1)
    if grain == "quarter":
        return date.replace(month=((date.month - 1) // 3) * 3 + 1, day=1)
    if grain == "year":
        return date.replace(month=1, day=1)

    raise ParameterDomainError(f"unsupported temporal grain {grain!r} for a parameter domain")


def _normalize(value: Any, param_type: LiteralParamType, is_temporal: bool) -> Any:
    """Turn one raw backend value into the canonical Python value.

    THE parity point — every backend's output passes through here, so all three
    converge on the same objects.
    """
    if is_temporal or param_type == "date":
        if param_type == "number":
            raise ParameterDomainError(
                f"{value!r} is a date, not a number; a `number` parameter's domain "
                "field must hold numeric values"
            )
        return _to_date(value).isoformat()

    if param_type == "number":
        # isinstance(True, int) is True and float(True) is 1.0 — guard bool
        # explicitly, as RangeBounds._comparable does for the same reason.
        if isinstance(value, bool):
            raise ParameterDomainError(f"{value!r} is a boolean, not a number")
        try:
            number = float(value)
        except (TypeError, ValueError) as e:
            raise ParameterDomainError(
                f"{value!r} is not a number; a `number` parameter's domain field "
                "must hold numeric values"
            ) from e
        # 2023 and 2023.0 must not read differently on different backends.
        return int(number) if number.is_integer() else number

    return value if isinstance(value, str) else str(value)


# ─── Backends ─────────────────────────────────────────────────────


def _inline_domain(
    model: DataModel,
    field_ref: str,
    resolver: ModelResolver,
    *,
    kind: DomainKind,
    data_base_dir: Path | None,
) -> list[Any] | tuple[Any, Any]:
    """The inline (JSON-rows) backend.

    Inline models are NOT in the adapter registry — `resolve_model_data`
    special-cases InlineSource (shelves/pipeline.py) and this mirrors that.
    Registering an "inline" adapter would change `resolve_data`'s
    NoDataSourceError behavior for inline models.

    Inline is also the only backend without truncation for free: DuckDB has
    DATE_TRUNC, Cube has timeDimensions[].granularity, and inline rows are raw
    JSON — so the grain is applied here in Python.
    """
    assert isinstance(model.source, InlineSource)

    path = Path(model.source.path)
    if data_base_dir is not None and not path.is_absolute():
        path = data_base_dir / path
    if not path.exists():
        raise ParameterDomainError(f"data file for model {model.model!r} not found: {path}.")

    rows = json.loads(path.read_text())

    base = resolver.resolve_base_field(field_ref)
    grain = resolver.resolve_grain(field_ref)
    dim = model.dimensions.get(base)
    # Inline JSON keys are DSL field names; `column` is honored defensively for
    # models that set one anyway.
    column = dim.column if dim is not None and dim.column else base

    raw = [row.get(column) for row in rows]
    raw = [v for v in raw if v is not None]
    if grain is not None:
        raw = [_truncate(v, grain) for v in raw]

    if kind == "values":
        # De-duplication happens in resolve_field_domain, alongside the other
        # two backends' results.
        return raw
    return (min(raw), max(raw)) if raw else (None, None)


def _domain_adapter(source_type: str, data_base_dir: Path | None) -> DataSourceAdapter:
    """Get the adapter for a source type, DuckDB-aware.

    The registered "file" adapter is a singleton pinned to `Path.cwd()`, so it
    ignores `data_base_dir`. A fresh DuckDBAdapter is constructed instead —
    using the registry instance here would make file-backed domains resolve
    only when the process happens to run from the right directory.
    """
    if source_type == "file":
        return DuckDBAdapter(base_dir=data_base_dir)
    return get_adapter(source_type)


# ─── Public API ───────────────────────────────────────────────────


def resolve_field_domain(
    ref: FieldRef,
    param_type: LiteralParamType,
    *,
    models_dir: Path | str | None = None,
    data_base_dir: Path | None = None,
) -> Domain:
    """Resolve ONE `{model, field}` reference to a Domain.

    Raises UNPREFIXED ParameterDomainError and adapter errors — the caller adds
    the `parameters.<name>: ` prefix, because only it knows the name.
    """
    assert ref.field is not None, "SHE-89 guarantees a field on string/number/date"

    model = load_model(ref.model, models_dir=models_dir)
    resolver = ModelResolver(model)
    source = f"{ref.model}.{ref.field}"

    # Pass the field reference WHOLE — the dot is a grain suffix, not model
    # qualification, and ModelResolver is the only thing allowed to read it.
    try:
        field_type = resolver.resolve_type(ref.field)
    except ValueError as e:
        raise ParameterDomainError(str(e)) from e

    if resolver.is_measure(ref.field):
        raise ParameterDomainError(
            f"{ref.field!r} is a measure. A parameter domain can only be sourced "
            "from a dimension — a measure's range depends on how a chart "
            "aggregates it, and the three data backends do not agree on what "
            "that means. Use an explicit min/max range, or point at a dimension."
        )

    kind: DomainKind = "values" if param_type == "string" else "bounds"
    is_temporal = field_type == "temporal"

    if model.source is None:
        raise ParameterDomainError(
            f"model {ref.model!r} has no 'source:' block, so its field domains "
            "cannot be resolved from data. Add a source to the model, or list "
            "the parameter's values explicitly."
        )

    if isinstance(model.source, InlineSource):
        raw = _inline_domain(model, ref.field, resolver, kind=kind, data_base_dir=data_base_dir)
    else:
        adapter = _domain_adapter(model.source.type, data_base_dir)
        raw = (
            adapter.fetch_domain_values(
                model, ref.field, resolver, limit=MAX_DOMAIN_CARDINALITY + 1
            )
            if kind == "values"
            else adapter.fetch_domain_bounds(model, ref.field, resolver)
        )

    # ── ONE normalizer, all backends — the parity guarantee ──
    if kind == "values":
        assert isinstance(raw, list)
        # sorted(set(...)) both de-duplicates (inline rows are raw) and orders
        # in Python, because no backend's collation is trusted.
        values = sorted({_normalize(v, param_type, is_temporal) for v in raw if v is not None})
        if not values:
            raise ParameterDomainError(_EMPTY_MESSAGE.format(source=source))
        if len(values) > MAX_DOMAIN_CARDINALITY:
            raise ParameterDomainError(
                _CARDINALITY_MESSAGE.format(source=source, limit=MAX_DOMAIN_CARDINALITY + 1)
            )
        return Domain(kind="values", param_type=param_type, source=source, values=values)

    low, high = raw
    if low is None or high is None:
        raise ParameterDomainError(_EMPTY_MESSAGE.format(source=source))
    return Domain(
        kind="bounds",
        param_type=param_type,
        source=source,
        min=_normalize(low, param_type, is_temporal),
        max=_normalize(high, param_type, is_temporal),
    )


def resolve_parameter_domains(
    parameters: ParametersBlock,
    *,
    models_dir: Path | str | None = None,
    data_base_dir: Path | None = None,
    validate_defaults: bool = True,
) -> dict[str, Domain]:
    """Resolve every field-reference `values:` in `parameters` to a real domain.

    Only `string` / `number` / `date` parameters whose `values:` is a single
    FieldRef are resolved. Literal lists, ranges, omitted `values:`, and every
    `type: field` parameter are skipped — they need no data.

    `models_dir` and `data_base_dir` MUST be the same values the caller passes
    to `compile_dashboard_charts`, so compilation and domain resolution can
    never read different model universes.

    Args:
        parameters: The block from `load_parameters(...)`.
        models_dir: Model manifest directory.
        data_base_dir: Base directory for relative inline/file source paths.
        validate_defaults: When True, each resolved parameter's `default` is
            checked against its domain. Turn off only for tooling that wants
            the domains without enforcing declarations.

    Returns:
        {parameter_name: Domain} — only for parameters that HAVE a domain. A
        parameter absent from this dict is unconstrained or literally
        constrained; that is not an error.

    Raises:
        ParameterDomainError: any resolution or validation failure. Every
            message is prefixed `parameters.<name>: `.
    """
    out: dict[str, Domain] = {}
    memo: dict[tuple[str, str, str], Domain] = {}

    for name, param in parameters.items():
        entries = param.values or []

        if isinstance(param, FieldParameter):
            # `type: field` never touches data — its values are field NAMES,
            # checked against the manifest by load_parameters(validate_fields).
            # The one case SHE-89 deferred is a bare {model: X} entry, whose
            # default it could not check without a models_dir.
            if len(entries) == 1 and isinstance(entries[0], FieldRef) and entries[0].field is None:
                with _attributed(name):
                    _check_default_is_a_field(param, entries[0].model, models_dir=models_dir)
            continue

        if len(entries) != 1 or not isinstance(entries[0], FieldRef):
            continue

        ref = entries[0]
        assert ref.field is not None  # SHE-89 guarantees this on literal types

        key = (ref.model, ref.field, param.type)
        domain = memo.get(key)
        if domain is None:
            with _attributed(name):
                domain = resolve_field_domain(
                    ref,
                    param.type,
                    models_dir=models_dir,
                    data_base_dir=data_base_dir,
                )
            memo[key] = domain

        out[name] = domain

        if validate_defaults and param.default is not None:
            check_value_in_domain(name, param.default, domain)

    return out


def check_value_in_domain(param_name: str, value: Any, domain: Domain) -> None:
    """Raise ParameterDomainError if `value` is outside `domain`.

    Used for the declaration-time `default` check, and reused for `--param`
    overrides (SHE-91) so both reject exactly the same things.
    """
    if value is None:
        return  # null means unset

    # Normalizing is REQUIRED, not cosmetic: a YAML `default: 2024-02-01`
    # arrives as a datetime.date while the domain holds ISO strings, and
    # comparing the two raises TypeError.
    normalized = _normalize(value, domain.param_type, domain.param_type == "date")

    if domain.kind == "values":
        values = domain.values or []
        if normalized in values:
            return
        shown = values[:10]
        lead = "Valid values" if len(values) <= 10 else "Valid values include"
        raise ParameterDomainError(
            f"parameters.{param_name}: default {_fmt(value)} is not in the domain "
            f"of {domain.source!r}. {lead}: "
            f"{', '.join(str(v) for v in shown)} ({len(values)} total)."
        )

    if domain.min <= normalized <= domain.max:
        return
    raise ParameterDomainError(
        f"parameters.{param_name}: default {_fmt(value)} is outside the domain of "
        f"{domain.source!r} (min: {domain.min}, max: {domain.max})."
    )


# ─── Private helpers ──────────────────────────────────────────────


@contextmanager
def _attributed(name: str) -> Iterator[None]:
    """Prefix any resolution failure with the parameter it came from.

    `resolve_field_domain` and the adapters raise unprefixed — they do not know
    the parameter name — so a Cube or DuckDB typed error would otherwise reach
    the author un-attributed.
    """
    try:
        yield
    except (ParameterDomainError, ShelvesError, ValueError) as e:
        raise ParameterDomainError(f"parameters.{name}: {e}") from e


def _check_default_is_a_field(
    param: FieldParameter,
    model_name: str,
    *,
    models_dir: Path | str | None,
) -> None:
    """A bare `{model: X}` entry means "any field in that model" — so the
    default must name one. A manifest read, never a query.
    """
    model = load_model(model_name, models_dir=models_dir)
    if param.default in model.measures or param.default in model.dimensions:
        return
    raise ParameterDomainError(
        f"default {param.default!r} is not a field in model {model_name!r}.\n"
        f"Available measures: {', '.join(sorted(model.measures))}.\n"
        f"Available dimensions: {', '.join(sorted(model.dimensions))}."
    )
