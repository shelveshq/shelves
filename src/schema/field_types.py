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
