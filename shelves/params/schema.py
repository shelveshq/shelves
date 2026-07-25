"""
Parameter Schema

Standalone, Tableau-style parameters — a project-level entity declared in
`parameters.yaml` beside the semantic models, referenced from charts with
`$name`. Four types, four keys.

`values:` is always a LIST. An entry is a literal scalar, a field reference
(`model` + `field`), or a range (`min` + `max`), written in YAML block style
like the rest of the DSL. Every model reference is explicit: the file has no
ambient model context, so there is no bare-string form to disambiguate.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

ParamType = Literal["string", "number", "date", "field"]

_VALUES_MUST_BE_LIST = (
    "'values' must be a list. Write entries with YAML dashes:\n"
    "  values:\n"
    "    - model: orders\n"
    "      field: region"
)


class FieldRef(BaseModel):
    """A model/field entry in a `values:` list.

    `field` is stored verbatim, including any temporal grain suffix
    ("week.month"). It is NOT split here — SHE-90 hands the whole string to
    ModelResolver._lookup, which already understands grain suffixes.

    `field` is optional: a bare `model` entry means "any field in that model",
    valid only on `type: field`.
    """

    model: str = Field(min_length=1)
    field: str | None = None


class RangeBounds(BaseModel):
    """A min/max entry in a `values:` list — continuous bounds.

    Bounds are numeric or dates. YAML turns an unquoted ISO date into a
    `datetime.date`, so that type is accepted alongside `str`.

    `step` is accepted and stored but unused here; it is a control-rendering
    hint for SHE-92.
    """

    min: float | int | str | dt.date
    max: float | int | str | dt.date
    step: float | int | None = None

    @model_validator(mode="after")
    def min_below_max(self) -> RangeBounds:
        if _comparable(self.min, self.max) and self.min >= self.max:  # type: ignore[operator]
            raise ValueError(f"min ({self.min}) must be less than max ({self.max})")
        return self


def _fmt(value: Any) -> str:
    """Render a value for an error message — ISO for dates, repr otherwise.

    Without this a date reads `datetime.date(2030, 1, 1)` beside bounds that
    read `2024-01-01`. `shelves.data.domains.check_value_in_domain` uses the
    same helper so domain and range errors read alike.
    """
    if isinstance(value, dt.date):
        return value.isoformat()
    return repr(value)


def _comparable(lo: Any, hi: Any) -> bool:
    """True when two bounds can be ordered without a type error."""
    numeric = (int, float)
    if isinstance(lo, bool) or isinstance(hi, bool):
        return False
    if isinstance(lo, numeric) and isinstance(hi, numeric):
        return True
    return isinstance(lo, dt.date) and isinstance(hi, dt.date)


ValuesEntry = FieldRef | RangeBounds | Any
ValuesSpec = list[ValuesEntry]


def _coerce_entries(raw: Any) -> Any:
    """Turn mapping entries in a `values:` list into FieldRef / RangeBounds.

    Dispatch is by key presence: `model` → FieldRef, `min`+`max` → RangeBounds.
    Scalars pass through as literals.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(_VALUES_MUST_BE_LIST)

    out: list[Any] = []
    for entry in raw:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        keys = set(entry)
        if "model" in keys:
            out.append(FieldRef(**entry))
        elif {"min", "max"} <= keys:
            out.append(RangeBounds(**entry))
        else:
            raise ValueError(
                f"unrecognized 'values' entry {entry!r}. An entry is a literal "
                "value, a field reference (model + field), or a range "
                "(min + max)."
            )
    return out


def _kind(entry: Any) -> str:
    if isinstance(entry, RangeBounds):
        return "range"
    if isinstance(entry, FieldRef):
        return "ref"
    return "literal"


class _ParameterBase(BaseModel):
    type: ParamType
    # No assignment: `default` is required on every parameter — a bare
    # annotation keeps it required in Pydantic while letting subclasses narrow
    # the type without pyright flagging a missing default on the override.
    default: Any
    label: str | None = None
    values: ValuesSpec | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_values(cls, data: Any) -> Any:
        if isinstance(data, dict) and "values" in data:
            data = {**data, "values": _coerce_entries(data["values"])}
        return data

    @model_validator(mode="after")
    def _values_not_empty_list(self) -> _ParameterBase:
        if self.values is not None and not self.values:
            raise ValueError("'values' must not be an empty list")
        return self

    @model_validator(mode="after")
    def _entries_are_homogeneous(self) -> _ParameterBase:
        """All literals, all field refs, or exactly one range.

        The three kinds mean different things — an enumerated value set, a
        sourced domain, continuous bounds — so a mixed list has no coherent
        reading.
        """
        if not self.values:
            return self
        kinds = {_kind(v) for v in self.values}
        if len(kinds) > 1:
            raise ValueError(
                "'values' mixes entry kinds. Use either literal values, or "
                "field references (model/field), or a single min/max range — "
                "not a combination."
            )
        if "range" in kinds and len(self.values) > 1:
            raise ValueError("'values' takes at most one min/max range entry.")
        return self

    @model_validator(mode="after")
    def _literal_types_take_one_ref(self) -> _ParameterBase:
        """At most ONE field reference on string/number/date.

        A domain comes from a single field. Gated on `type` because Pydantic
        runs base-class validators on subclasses too — FieldParameter allows
        many refs and must not trip this.
        """
        if self.type == "field":
            return self
        refs = [v for v in (self.values or []) if isinstance(v, FieldRef)]
        if len(refs) > 1:
            raise ValueError(
                f"type {self.type!r} takes at most one field reference — a "
                "domain comes from a single field. Multiple model/field "
                "entries are only valid when type is 'field'."
            )
        if refs and refs[0].field is None:
            raise ValueError(
                "a field reference needs 'field' — a bare 'model' entry (any "
                "field in the model) is only valid when type is 'field'."
            )
        return self

    @model_validator(mode="after")
    def _default_within_values(self) -> _ParameterBase:
        """Check `default` against LITERAL constraints only.

        A field-reference domain cannot be checked without a data connection —
        that is SHE-90. A null default is permitted here; FieldParameter
        forbids it separately.
        """
        if self.default is None or not self.values:
            return self

        first = self.values[0]

        if isinstance(first, FieldRef):
            return self

        if isinstance(first, RangeBounds):
            in_bounds = (
                not (_comparable(first.min, self.default) and _comparable(self.default, first.max))
                or first.min <= self.default <= first.max  # type: ignore[operator]
            )
            if not in_bounds:
                raise ValueError(
                    f"default {_fmt(self.default)} is outside the range "
                    f"min: {_fmt(first.min)}, max: {_fmt(first.max)}"
                )
            return self

        if self.default not in self.values:
            raise ValueError(f"default {_fmt(self.default)} is not in values {self.values!r}")
        return self


class StringParameter(_ParameterBase):
    type: Literal["string"]
    default: str | None


class NumberParameter(_ParameterBase):
    type: Literal["number"]
    default: float | int | None


class DateParameter(_ParameterBase):
    type: Literal["date"]
    default: dt.date | str | None


class FieldParameter(_ParameterBase):
    """A parameter whose value is a field NAME — the measure/dimension swapper."""

    type: Literal["field"]
    # Annotated as optional so a null default produces the explanatory error
    # below rather than Pydantic's generic "should be a valid string".
    default: str | None

    @model_validator(mode="after")
    def _requires_field_references(self) -> FieldParameter:
        if self.default is None:
            raise ValueError(
                "type 'field' requires a non-null default — a shelf cannot be "
                "empty. null (meaning 'unset') is only valid for string, "
                "number, and date parameters."
            )
        if not self.values:
            raise ValueError(
                "type 'field' requires 'values' — there is no way to reference "
                "a field without naming its model. Add entries with a model "
                "and a field, or a bare model entry to allow any field in it."
            )
        if any(isinstance(v, RangeBounds) for v in self.values):
            raise ValueError(
                "a min/max range is not valid when type is 'field'. Use model/field entries."
            )
        if any(not isinstance(v, FieldRef) for v in self.values):
            raise ValueError(
                "type 'field' needs field references, not literal values. Each "
                "entry needs a model and a field."
            )

        names = [v.field for v in self.values if isinstance(v, FieldRef)]
        if None in names:
            if len(names) > 1:
                raise ValueError(
                    "a bare 'model' entry means 'any field in that model' and "
                    "must be the only entry."
                )
            # Any field in the model is allowed — SHE-90 validates the default.
            return self

        if self.default not in names:
            raise ValueError(f"default {_fmt(self.default)} is not in values {names!r}")
        return self


ParameterDef = Annotated[
    StringParameter | NumberParameter | DateParameter | FieldParameter,
    Field(discriminator="type"),
]


def validate_value(param: _ParameterBase, value: Any) -> None:
    """Raise ValueError if `value` violates the parameter's `values` constraint.

    Shared by the declaration-time `default` check and the runtime override
    check in ParameterSet, so both reject exactly the same things. Only
    literal and range constraints are enforced — resolving a field-reference
    domain needs a data connection (SHE-90).
    """
    if value is None:
        if isinstance(param, FieldParameter):
            raise ValueError("type 'field' requires a non-null value — a shelf cannot be empty.")
        return

    if not param.values:
        return

    first = param.values[0]

    if isinstance(first, FieldRef):
        names = [v.field for v in param.values if isinstance(v, FieldRef)]
        if isinstance(param, FieldParameter) and None not in names and value not in names:
            raise ValueError(f"{_fmt(value)} is not in values {names!r}")
        return

    if isinstance(first, RangeBounds):
        in_bounds = (
            not (_comparable(first.min, value) and _comparable(value, first.max))
            or first.min <= value <= first.max  # type: ignore[operator]
        )
        if not in_bounds:
            raise ValueError(
                f"{_fmt(value)} is outside the range min: {_fmt(first.min)}, max: {_fmt(first.max)}"
            )
        return

    if value not in param.values:
        raise ValueError(f"{_fmt(value)} is not in values {param.values!r}")


ParametersBlock = dict[str, ParameterDef]


class ParametersFile(BaseModel):
    """Root of parameters.yaml."""

    parameters: ParametersBlock = Field(default_factory=dict)
