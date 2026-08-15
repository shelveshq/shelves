"""
Parameter Domain Resolution

Resolves field-reference `values:` entries to real domains across all three
backends (inline, DuckDB, Cube). One normalizer — `_normalize` — so backends
converge on the same Python objects.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import warnings
from collections.abc import Generator
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

DOMAIN_CACHE_TTL: float = 60.0

# Cached value carries the domain, the insert time, and any warnings emitted
# while it was resolved (e.g. cardinality truncation). The warnings are re-emitted
# on every cache hit — otherwise a condition that still holds (a >500-value field
# truncated on the first compile) goes silent on the next recompile within the
# TTL, and its Studio marker is cleared while the truncation is still in effect.
_domain_cache: dict[tuple[str, str, str, str], tuple[Domain, float, tuple[str, ...]]] = {}


def clear_domain_cache() -> None:
    _domain_cache.clear()


_CARDINALITY_WARNING = (
    "field {source!r} has {count} distinct values — truncated to the first "
    "{limit}. Consider mode: wildcard for free-text search, or a calculated "
    "dimension that buckets the values."
)

_CARDINALITY_WARNING_APPROX = (
    "field {source!r} has more than {limit} distinct values — truncated to the first "
    "{limit}. Consider mode: wildcard for free-text search, or a calculated "
    "dimension that buckets the values."
)

_EMPTY_MESSAGE = (
    "field {source!r} resolved to an empty domain — the data source returned no values."
)


@dataclass(frozen=True)
class Domain:
    """A parameter's value space, resolved from data at compile time."""

    kind: DomainKind
    param_type: LiteralParamType
    source: str
    values: list[Any] | None = None
    min: Any = None
    max: Any = None
    truncated: bool = False


_ISO_PREFIX_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


def _to_date(value: Any) -> dt.date:
    """Coerce a backend temporal value to a datetime.date."""
    # datetime is a subclass of date — check FIRST.
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value

    match = _ISO_PREFIX_RE.match(str(value))
    if match is None:
        raise ValueError(f"{value!r} is not a recognizable date")
    return dt.date(int(match[1]), int(match[2] or 1), int(match[3] or 1))


def _truncate(value: Any, grain: str | None) -> dt.date:
    """Truncate a date to the start of its grain (weeks start Monday)."""
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
    """Turn one raw backend value into the canonical Python value."""
    if is_temporal or param_type == "date":
        if param_type == "number":
            raise ParameterDomainError(
                f"{value!r} is a date, not a number; a `number` parameter's domain "
                "field must hold numeric values"
            )
        return _to_date(value).isoformat()

    if param_type == "number":
        if isinstance(value, bool):
            raise ParameterDomainError(f"{value!r} is a boolean, not a number")
        try:
            number = float(value)
        except (TypeError, ValueError) as e:
            raise ParameterDomainError(
                f"{value!r} is not a number; a `number` parameter's domain field "
                "must hold numeric values"
            ) from e
        return int(number) if number.is_integer() else number

    return value if isinstance(value, str) else str(value)


def _inline_domain(
    model: DataModel,
    field_ref: str,
    resolver: ModelResolver,
    *,
    kind: DomainKind,
    data_base_dir: Path | None,
) -> list[Any] | tuple[Any, Any]:
    """Resolve a domain from inline JSON rows."""
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
    column = dim.column if dim is not None and dim.column else base

    raw = [row.get(column) for row in rows]
    raw = [v for v in raw if v is not None]
    if grain is not None:
        raw = [_truncate(v, grain) for v in raw]

    if kind == "values":
        return raw
    return (min(raw), max(raw)) if raw else (None, None)


def _domain_adapter(source_type: str, data_base_dir: Path | None) -> DataSourceAdapter:
    # Fresh DuckDBAdapter so data_base_dir is honored (the registry singleton uses cwd).
    if source_type == "file":
        return DuckDBAdapter(base_dir=data_base_dir)
    return get_adapter(source_type)


def resolve_field_domain(
    ref: FieldRef,
    param_type: LiteralParamType,
    *,
    models_dir: Path | str | None = None,
    data_base_dir: Path | None = None,
) -> Domain:
    """Resolve one `{model, field}` reference to a Domain."""
    assert ref.field is not None

    model = load_model(ref.model, models_dir=models_dir)

    source_type = (
        "inline"
        if isinstance(model.source, InlineSource)
        else (model.source.type if model.source is not None else "none")
    )
    # Key omits models_dir/data_base_dir — safe because each process (Studio,
    # dev server) binds a single project directory for its lifetime.
    cache_key = (source_type, ref.model, ref.field, param_type)
    cached = _domain_cache.get(cache_key)
    if cached is not None:
        domain, ts, cached_warnings = cached
        if time.monotonic() - ts <= DOMAIN_CACHE_TTL:
            # Re-emit warnings so a truncation notice survives across recompiles.
            for msg in cached_warnings:
                warnings.warn(msg, stacklevel=2)
            return domain

    resolver = ModelResolver(model)
    source = f"{ref.model}.{ref.field}"
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

    # Warnings emitted while resolving are cached with the domain so a later
    # cache hit can replay them (see the cache-hit block above).
    emitted_warnings: list[str] = []
    if kind == "values":
        assert isinstance(raw, list)
        values = sorted({_normalize(v, param_type, is_temporal) for v in raw if v is not None})
        if not values:
            raise ParameterDomainError(_EMPTY_MESSAGE.format(source=source))
        if len(values) > MAX_DOMAIN_CARDINALITY:
            if len(values) == MAX_DOMAIN_CARDINALITY + 1 and not isinstance(
                model.source, InlineSource
            ):
                msg = _CARDINALITY_WARNING_APPROX.format(
                    source=source, limit=MAX_DOMAIN_CARDINALITY
                )
            else:
                msg = _CARDINALITY_WARNING.format(
                    source=source, count=len(values), limit=MAX_DOMAIN_CARDINALITY
                )
            warnings.warn(msg, stacklevel=2)
            emitted_warnings.append(msg)
            values = values[:MAX_DOMAIN_CARDINALITY]
            was_truncated = True
        else:
            was_truncated = False
        domain = Domain(
            kind="values",
            param_type=param_type,
            source=source,
            values=values,
            truncated=was_truncated,
        )
    else:
        low, high = raw
        if low is None or high is None:
            raise ParameterDomainError(_EMPTY_MESSAGE.format(source=source))
        domain = Domain(
            kind="bounds",
            param_type=param_type,
            source=source,
            min=_normalize(low, param_type, is_temporal),
            max=_normalize(high, param_type, is_temporal),
        )

    _domain_cache[cache_key] = (domain, time.monotonic(), tuple(emitted_warnings))
    return domain


def resolve_parameter_domains(
    parameters: ParametersBlock,
    *,
    models_dir: Path | str | None = None,
    data_base_dir: Path | None = None,
    validate_defaults: bool = True,
) -> dict[str, Domain]:
    """Resolve every field-reference `values:` entry to a real domain.

    Returns {name: Domain} only for parameters whose `values:` is a single
    FieldRef. Literal lists, ranges, and `type: field` are skipped.
    """
    out: dict[str, Domain] = {}

    for name, param in parameters.items():
        entries = param.values or []

        if isinstance(param, FieldParameter):
            if len(entries) == 1 and isinstance(entries[0], FieldRef) and entries[0].field is None:
                with _attributed(name):
                    _check_default_is_a_field(param, entries[0].model, models_dir=models_dir)
            continue

        if len(entries) != 1 or not isinstance(entries[0], FieldRef):
            continue

        ref = entries[0]
        assert ref.field is not None

        with _attributed(name):
            domain = resolve_field_domain(
                ref,
                param.type,
                models_dir=models_dir,
                data_base_dir=data_base_dir,
            )

        out[name] = domain

        if validate_defaults and param.default is not None:
            check_value_in_domain(name, param.default, domain)

    return out


def check_value_in_domain(
    param_name: str, value: Any, domain: Domain, *, label: str = "default"
) -> None:
    """Raise ParameterDomainError if `value` is outside `domain`."""
    if value is None:
        return

    normalized = _normalize(value, domain.param_type, domain.param_type == "date")

    if domain.kind == "values":
        if domain.truncated:
            # A prefix cannot disprove membership, so accept — but say so, or a
            # typo'd value silently resolves to nothing on a wide field.
            if normalized not in (domain.values or []):
                warnings.warn(
                    f"parameters.{param_name}: {label} {_fmt(value)} was not checked "
                    f"against {domain.source!r} — its domain was truncated at "
                    f"{MAX_DOMAIN_CARDINALITY} values, so membership is unknown.",
                    stacklevel=2,
                )
            return
        values = domain.values or []
        if normalized in values:
            return
        shown = values[:10]
        lead = "Valid values" if len(values) <= 10 else "Valid values include"
        raise ParameterDomainError(
            f"parameters.{param_name}: {label} {_fmt(value)} is not in the domain "
            f"of {domain.source!r}. {lead}: "
            f"{', '.join(str(v) for v in shown)} ({len(values)} total)."
        )

    if domain.min <= normalized <= domain.max:
        return
    raise ParameterDomainError(
        f"parameters.{param_name}: {label} {_fmt(value)} is outside the domain of "
        f"{domain.source!r} (min: {domain.min}, max: {domain.max})."
    )


@contextmanager
def _attributed(name: str) -> Generator[None]:
    """Prefix resolution failures with the parameter name."""
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
    model = load_model(model_name, models_dir=models_dir)
    if param.default in model.measures or param.default in model.dimensions:
        return
    raise ParameterDomainError(
        f"default {param.default!r} is not a field in model {model_name!r}.\n"
        f"Available measures: {', '.join(sorted(model.measures))}.\n"
        f"Available dimensions: {', '.join(sorted(model.dimensions))}."
    )
