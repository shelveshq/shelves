"""
Parameters File Loader

Loads `parameters.yaml` — the project-level parameter declarations that sit
beside the semantic models. Mirrors `shelves/models/loader.py`: same
`DEFAULT_*` constant pattern, same `Path | str | None` argument style.

A missing file is NOT an error. It means the project declares no parameters,
which is what every project looked like before SHE-89.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from shelves.params.schema import FieldParameter, FieldRef, ParametersBlock, ParametersFile

DEFAULT_PARAMETERS_FILENAME = "parameters.yaml"


def default_parameters_path(models_dir: Path | str | None = None) -> Path:
    """`<models_dir>/parameters.yaml`, defaulting to the models directory."""
    from shelves.models.loader import DEFAULT_MODELS_DIR

    base = Path(models_dir).resolve() if models_dir else DEFAULT_MODELS_DIR
    return base / DEFAULT_PARAMETERS_FILENAME


def load_parameters(
    path: Path | str | None = None,
    *,
    models_dir: Path | str | None = None,
    validate_fields: bool = False,
) -> ParametersBlock:
    """Load and validate a parameters.yaml file.

    Args:
        path: Explicit file path. None → `default_parameters_path(models_dir)`.
        models_dir: Locates the default file, and resolves model names when
                    `validate_fields` is True.
        validate_fields: When True, every field parameter's model is loaded and
                    each referenced field name checked against it. Off by
                    default so the loader works with no model directory.

    Returns:
        ParametersBlock — an empty dict if the file does not exist.

    Raises:
        ValueError: the file is present but invalid, or a referenced model or
                    field does not exist (only when validate_fields is True).
    """
    target = Path(path) if path is not None else default_parameters_path(models_dir)

    if not target.exists():
        return {}

    try:
        raw = yaml.safe_load(target.read_text()) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML syntax in {target}: {e}") from e

    try:
        parsed = ParametersFile.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"Invalid parameters file {target}: {e}") from e

    if validate_fields:
        _validate_field_names(parsed.parameters, models_dir=models_dir)

    return parsed.parameters


def _validate_field_names(
    params: ParametersBlock,
    *,
    models_dir: Path | str | None,
) -> None:
    """Check every field parameter's references resolve in their model.

    Names only — this never queries data. Resolving a reference to its actual
    domain (distinct values, bounds) is SHE-90.
    """
    from shelves.models.loader import load_model
    from shelves.models.resolver import ModelResolver

    for name, param in params.items():
        if not isinstance(param, FieldParameter):
            continue
        for entry in param.values or []:
            if not isinstance(entry, FieldRef):
                continue
            try:
                model = load_model(entry.model, models_dir=models_dir)
            except FileNotFoundError as e:
                raise ValueError(
                    f"parameters.{name}: model {entry.model!r} not found "
                    f"in {models_dir or 'the models directory'}."
                ) from e

            if entry.field is None:
                continue

            resolver = ModelResolver(model)
            try:
                resolver.resolve(entry.field)
            except ValueError as e:
                raise ValueError(
                    f"parameters.{name}: {entry.field!r} is not a field in "
                    f"model {entry.model!r}. "
                    f"Available measures: {', '.join(sorted(model.measures))}."
                ) from e
