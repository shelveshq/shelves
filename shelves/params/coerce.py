"""
CLI/string → declared-type coercion for parameter overrides.

Overrides arrive as strings from every surface that can supply them (CLI flags
today; Studio controls and URL state later). Coercion is driven by the DECLARED
type, never inferred from the string — `--param status=10` stays the string
"10" because `status` is `type: string`.

Coercion does NOT validate. `ParameterSet.__init__` owns the `values:` check, so
both the declaration-time `default` check and the runtime override check reject
exactly the same things.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from shelves.params.schema import (
    DateParameter,
    FieldParameter,
    FieldRef,
    NumberParameter,
    ParameterDef,
    ParametersBlock,
    RangeBounds,
    _fmt,
)

NULL_TOKEN = "null"
"""The literal string that clears a value. YAML's own spelling for None."""


def parse_param_flags(pairs: Sequence[str]) -> dict[str, str]:
    """Turn repeated `--param key=value` strings into a mapping.

    Splits on the FIRST `=` only, so values may contain `=`. A later
    occurrence of a key overwrites an earlier one (last wins).

    Raises:
        ValueError: an entry has no `=`, or an empty key.
    """
    out: dict[str, str] = {}
    for raw in pairs:
        key, sep, value = raw.partition("=")
        if not sep or not key:
            raise ValueError(f"--param {raw}: expected key=value, e.g. --param metric=revenue.")
        out[key] = value
    return out


def describe_values(param: ParameterDef) -> str:
    """A one-clause description of a parameter's valid space, or "".

    Appended to coercion errors so the message names the valid alternatives.
    Never raises; an undescribable constraint yields "".
    """
    if not param.values:
        return ""

    first = param.values[0]

    if isinstance(first, RangeBounds):
        # _fmt renders a date as 2024-01-01, not datetime.date(2024, 1, 1).
        # Importing it across modules despite the underscore matches
        # shelves/data/domains.py, which already does exactly that.
        noun = "date" if isinstance(param, DateParameter) else "number"
        return f"Give a {noun} between {_fmt(first.min)} and {_fmt(first.max)}."

    if isinstance(first, FieldRef):
        names = [v.field for v in param.values if isinstance(v, FieldRef)]
        if None in names:
            return f"Allowed: any field in model {first.model!r}."
        if isinstance(param, FieldParameter):
            return f"Allowed values: {', '.join(n for n in names if n)}."
        # A literal type sourcing its domain from a field. The resolved domain
        # is NOT consulted here — describe_values takes only a ParameterDef, and
        # a coercion error means the string never became a comparable value in
        # the first place. When a value coerces but sits outside the domain,
        # check_value_in_domain reports it and lists the real values.
        return f"Allowed values come from {first.model}.{first.field}."

    return f"Allowed values: {', '.join(str(v) for v in param.values)}."


def coerce_override(name: str, param: ParameterDef, raw: str) -> Any:
    """Convert one raw string to the parameter's declared Python type.

    Raises:
        ValueError: the string cannot be read as the declared type. The message
            names the parameter and its valid space, with NO surface-specific
            prefix (see `describe_values`).
    """
    if raw == NULL_TOKEN:
        return None

    if isinstance(param, NumberParameter):
        try:
            return int(raw)  # keeps 25 an int, not 25.0
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            raise ValueError(
                f"parameters.{name}: {raw!r} is not a number. {describe_values(param)}".strip()
            ) from None

    if isinstance(param, DateParameter):
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            raise ValueError(
                f"parameters.{name}: {raw!r} is not a date. Use ISO format, "
                f"e.g. 2024-01-31. {describe_values(param)}".strip()
            ) from None

    return raw  # string and field both hold text


def coerce_overrides(
    declared: ParametersBlock,
    raw: Mapping[str, str],
) -> dict[str, Any]:
    """Coerce every override against its declaration.

    An UNDECLARED name is passed through unchanged — `ParameterSet.__init__`
    owns the "not a declared parameter" message, and raising a second, different
    one here is exactly the drift this ticket exists to remove.
    """
    return {k: (coerce_override(k, declared[k], v) if k in declared else v) for k, v in raw.items()}
