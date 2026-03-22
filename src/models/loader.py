"""
Data Model Loader

Reads data model manifest YAML files from a `models/` directory,
validates them via Pydantic, and caches the result in memory.

Usage:
    from src.models.loader import load_model, clear_model_cache

    model = load_model("orders")                          # loads models/orders.yaml
    model = load_model("orders", models_dir="path/to/")  # custom directory
    clear_model_cache()                                   # reset cache (use in tests)
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.models.schema import DataModel

# Module-level cache: cache_key → DataModel
# Cache key is "<resolved_dir>:<model_name>" to support multiple directories.
_cache: dict[str, DataModel] = {}

# Default models directory: <project_root>/models/
# Resolved relative to this file: src/models/loader.py → ../../models/
DEFAULT_MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"


def load_model(
    model_name: str,
    models_dir: Path | str | None = None,
) -> DataModel:
    """
    Load a data model manifest by name.

    Looks for `<models_dir>/<model_name>.yaml`, parses and validates it
    via Pydantic, checks that the `model` field matches the filename stem,
    caches the result in memory, and returns it.

    Args:
        model_name: The model identifier (e.g. "orders"). Used as the filename
                    stem — the file loaded will be `<models_dir>/orders.yaml`.
        models_dir: Directory containing model YAML files. Defaults to
                    `<project_root>/models/` when omitted.

    Returns:
        A validated DataModel instance.

    Raises:
        FileNotFoundError: If `<models_dir>/<model_name>.yaml` does not exist.
        ValueError: If the `model` field inside the YAML does not match `model_name`.
        pydantic.ValidationError: If the YAML fails Pydantic schema validation.
    """
    dir_path = Path(models_dir).resolve() if models_dir else DEFAULT_MODELS_DIR
    cache_key = f"{dir_path}:{model_name}"

    if cache_key in _cache:
        return _cache[cache_key]

    model_path = dir_path / f"{model_name}.yaml"
    if not model_path.exists():
        raise FileNotFoundError(f"Data model '{model_name}' not found at {model_path}")

    raw = yaml.safe_load(model_path.read_text())
    data_model = DataModel.model_validate(raw)

    if data_model.model != model_name:
        raise ValueError(
            f"Model name mismatch: file is '{model_name}.yaml' "
            f"but model field is '{data_model.model}'"
        )

    _cache[cache_key] = data_model
    return data_model


def clear_model_cache() -> None:
    """
    Clear the in-memory model cache.

    Call this in test teardown (or as a pytest autouse fixture) to prevent
    cached models from one test bleeding into another.
    """
    _cache.clear()
