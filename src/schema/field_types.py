"""
Field Type Resolution Protocol

Defines the FieldTypeResolver protocol that all resolvers must implement.
The concrete implementation is ModelResolver (src/models/resolver.py).
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

VegaLiteType = Literal["quantitative", "temporal", "nominal", "ordinal"]


@runtime_checkable
class FieldTypeResolver(Protocol):
    """Protocol for resolving field names to Vega-Lite types."""

    def resolve(self, field_name: str) -> VegaLiteType: ...

    def resolve_base_field(self, field_ref: str) -> str: ...

    def resolve_time_unit(self, field_ref: str) -> str | None: ...

    def resolve_label(self, field_ref: str) -> str: ...

    def resolve_format(self, field_ref: str) -> str | None: ...

    def resolve_default_sort(self, field_ref: str) -> str | None: ...

    def resolve_sort_order(self, field_ref: str) -> list[str] | None: ...

    def resolve_grain(self, field_ref: str) -> str | None: ...

    def is_measure(self, field_ref: str) -> bool: ...
