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

from shelves.models.loader import clear_model_cache, load_model
from shelves.models.resolver import ModelResolver
from shelves.models.schema import (
    CubeSource,
    DataModel,
    DimensionDefinition,
    FileSource,
    InlineSource,
    JoinDefinition,
    MeasureDefinition,
    ModelSource,
    NominalDimensionDefinition,
    TemporalDimensionDefinition,
)

__all__ = [
    "CubeSource",
    "DataModel",
    "DimensionDefinition",
    "FileSource",
    "InlineSource",
    "JoinDefinition",
    "MeasureDefinition",
    "ModelResolver",
    "ModelSource",
    "NominalDimensionDefinition",
    "TemporalDimensionDefinition",
    "clear_model_cache",
    "load_model",
]
