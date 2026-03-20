"""
Data Model Manifest — Centralized Field Definitions

Provides Pydantic models for data model YAML files and a loader
to read them from the `models/` directory.

Typical usage:
    from src.models import load_model, clear_model_cache

    model = load_model("orders")
    revenue_def = model.measures["revenue"]
    week_def = model.dimensions["week"]   # TemporalDimensionDefinition
"""

from src.models.schema import (
    CubeSource,
    DataModel,
    DimensionDefinition,
    InlineSource,
    MeasureDefinition,
    ModelSource,
    NominalDimensionDefinition,
    TemporalDimensionDefinition,
)
from src.models.loader import load_model, clear_model_cache
from src.models.resolver import ModelResolver

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
