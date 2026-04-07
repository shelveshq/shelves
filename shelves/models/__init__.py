"""
Data Model Manifest — Centralized Field Definitions

Provides Pydantic models for data model YAML files and a loader
to read them from the `models/` directory.

Typical usage:
    from shelves.models import load_model, clear_model_cache

    model = load_model("orders")
    revenue_def = model.measures["revenue"]
    week_def = model.dimensions["week"]   # TemporalDimensionDefinition
"""

from shelves.models.schema import (
    CubeSource,
    DataModel,
    DimensionDefinition,
    InlineSource,
    MeasureDefinition,
    ModelSource,
    NominalDimensionDefinition,
    TemporalDimensionDefinition,
)
from shelves.models.loader import load_model, clear_model_cache
from shelves.models.resolver import ModelResolver

__all__ = [
    "DataModel",
    "MeasureDefinition",
    "NominalDimensionDefinition",
    "TemporalDimensionDefinition",
    "DimensionDefinition",
    "InlineSource",
    "CubeSource",
    "ModelSource",
    "load_model",
    "clear_model_cache",
    "ModelResolver",
]
