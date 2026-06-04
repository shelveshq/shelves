"""
Chart Compilation Pipeline

Single source of truth for the chart compilation pipeline.
All CLI tools, the studio server, and the dashboard composer call these functions.
"""

from __future__ import annotations

import json
from pathlib import Path

from shelves.schema.chart_schema import ChartSpec, parse_chart
from shelves.theme.merge import load_theme, merge_theme
from shelves.theme.theme_schema import ThemeSpec
from shelves.translator.translate import translate_chart


def compile_chart(
    yaml_text: str,
    *,
    theme_path: Path | None = None,
    theme: ThemeSpec | None = None,
    no_theme: bool = False,
    models_dir: Path | str | None = None,
) -> tuple[dict, ChartSpec]:
    """
    Core chart pipeline: parse → translate → theme merge.

    Returns (vl_spec, chart_spec). The chart_spec is returned so callers
    can use spec.sheet for titles/filenames and spec.data for model loading.

    Does NOT bind data. Callers handle data resolution because each has
    different I/O requirements (--no-data flags, file paths, Cube queries).

    If both theme and theme_path are provided, theme wins (it's already loaded).

    Args:
        yaml_text: Raw YAML string for a chart spec.
        theme_path: Path to a custom theme YAML. None = use default theme.
        theme: Pre-loaded ThemeSpec. Takes priority over theme_path.
        no_theme: If True, skip theme merging entirely.
        models_dir: Directory containing model YAML files.

    Returns:
        Tuple of (vega_lite_spec_dict, parsed_chart_spec).

    Raises:
        pydantic.ValidationError: If the YAML is not a valid chart spec.
        yaml.YAMLError: If the YAML string is malformed.
        FileNotFoundError: If theme_path doesn't exist.
    """
    spec = parse_chart(yaml_text)

    if not no_theme and theme is None:
        theme = load_theme(theme_path)

    kpi_tokens = theme.chart.kpi if theme is not None else None
    vl_spec = translate_chart(spec, models_dir=models_dir, kpi_tokens=kpi_tokens)

    if not no_theme:
        vl_spec = merge_theme(vl_spec, theme)

    return vl_spec, spec


def resolve_model_data(
    vl_spec: dict,
    spec: ChartSpec,
    *,
    models_dir: Path | str | None = None,
    data_base_dir: Path | None = None,
) -> dict:
    """
    Resolve data from the chart's model source.

    Loads the model for spec.data, routes by source type:
    - inline: reads JSON from the source path and binds rows.
      If the file is missing, returns vl_spec unchanged (silent no-op).
    - cube/other: delegates to resolve_data, which may raise on failure.

    Callers should wrap in try/except for best-effort data binding.

    Args:
        vl_spec: Compiled Vega-Lite spec (no data yet).
        spec: Parsed ChartSpec (needed for field extraction).
        models_dir: Optional models directory path.
        data_base_dir: Base directory for resolving relative inline source
                      paths. If None, paths are resolved as-is.

    Returns:
        Vega-Lite spec, with data attached if resolution succeeded.
    """
    from shelves.data.bind import resolve_data
    from shelves.models.loader import load_model

    model = load_model(spec.data, models_dir=models_dir)

    if model.source and model.source.type == "inline":
        source_path = Path(model.source.path)
        if data_base_dir and not source_path.is_absolute():
            source_path = data_base_dir / source_path
        if source_path.exists():
            rows = json.loads(source_path.read_text())
            return resolve_data(vl_spec, spec, rows=rows)
        return vl_spec
    else:
        return resolve_data(vl_spec, spec, models_dir=models_dir)
