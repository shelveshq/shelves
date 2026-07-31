"""
Parameter Reference Positions

The allow-list of paths in a chart or dashboard spec where a `$ref` is legal,
and what kind of parameter each accepts.

**This is an allow-list, and that is load-bearing.** `classify()` returns None
for any path not listed, and None means forbidden. When a new DSL field lands,
parameters are rejected there until someone adds it here deliberately — the
safe default. Never make unknown paths permissive.

Path form: dotted keys with `[*]` for list indices, e.g. `rows[*].measure`.
`classify()` normalizes concrete indices (`rows[0]`) and free-form dict keys
(the dashboard components block) before lookup.
"""

from __future__ import annotations

import re
from typing import Literal

SlotKind = Literal["field", "literal", "interpolation"]

_INDEX_RE = re.compile(r"\[\d+\]")

# Positions holding a model field reference — `type: field` parameters only.
FIELD_SLOTS: frozenset[str] = frozenset(
    {
        "cols",
        "rows",
        "cols[*].measure",
        "rows[*].measure",
        "cols[*].layer[*].measure",
        "rows[*].layer[*].measure",
        "color",
        "color.field",
        "cols[*].color",
        "rows[*].color",
        "cols[*].layer[*].color",
        "rows[*].layer[*].color",
        "cols[*].color.field",
        "rows[*].color.field",
        "cols[*].layer[*].color.field",
        "rows[*].layer[*].color.field",
        "detail",
        "cols[*].detail",
        "rows[*].detail",
        "cols[*].layer[*].detail",
        "rows[*].layer[*].detail",
        "size",
        "cols[*].size",
        "rows[*].size",
        "cols[*].layer[*].size",
        "rows[*].layer[*].size",
        "facet.row",
        "facet.column",
        "facet.field",
        "sort.field",
        "tooltip[*]",
        "tooltip[*].field",
        "label.field",
        "cols[*].label.field",
        "rows[*].label.field",
        "cols[*].layer[*].label.field",
        "rows[*].layer[*].label.field",
        "kpi.value",
        "kpi.comparison.field",
        "filters[*].field",
    }
)

# Filter value positions — `string` / `number` / `date` parameters only.
# Note these are ELEMENT paths: the containing list (`filters[*].values`) is
# deliberately absent, because there is no list-valued parameter type.
LITERAL_SLOTS: frozenset[str] = frozenset(
    {
        "filters[*].value",
        "filters[*].values[*]",
        "filters[*].range[*]",
    }
)

# Title-class text — `${name}` interpolation, any parameter type.
# ChartSpec has no `title`/`subtitle`: the title is `sheet`, the subtitle is
# `description` (see shelves/translator/translate.py).
INTERPOLATION_SLOTS: frozenset[str] = frozenset(
    {
        "sheet",
        "description",
        "axis.x.title",
        "axis.y.title",
        "kpi.title",
        "kpi.comparison.label",
        # Dashboard-side
        "root.contains[*].text",
        "components.*.text",
    }
)


def normalize(path: str) -> str:
    """Collapse concrete list indices to `[*]`."""
    return _INDEX_RE.sub("[*]", path)


_NESTED_CONTAINS_RE = re.compile(
    r"^(?:root|components\.\*)(?:\.(horizontal|vertical))?(?:\.contains\[\*\]\.(horizontal|vertical))*\.contains\[\*\]\.text$"
)


def classify(path: str) -> SlotKind | None:
    """Slot kind for a dotted path, or None if a reference is forbidden there."""
    key = normalize(path)
    if key in FIELD_SLOTS:
        return "field"
    if key in LITERAL_SLOTS:
        return "literal"
    if key in INTERPOLATION_SLOTS:
        return "interpolation"
    # The dashboard components block is keyed by user-chosen names.
    if key.startswith("components."):
        generic = re.sub(r"^components\.[^.]+\.", "components.*.", key)
        if generic in INTERPOLATION_SLOTS:
            return "interpolation"
        key = generic
    # Dashboard text can nest arbitrarily inside horizontal/vertical containers.
    if _NESTED_CONTAINS_RE.match(key):
        return "interpolation"
    return None
