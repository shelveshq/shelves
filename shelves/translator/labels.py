from __future__ import annotations

from typing import Any, Literal

from shelves.schema.chart_schema import ChartSpec, LabelConfig, LabelSpec, MarkSpec
from shelves.schema.field_types import FieldTypeResolver

LABEL_POSITION_MAP: dict[tuple[str, str], dict[str, Any]] = {
    ("vertical", "top"): {"baseline": "bottom", "dy": -6},
    ("vertical", "bottom"): {"baseline": "top", "dy": 8},
    ("vertical", "inside-top"): {"baseline": "top", "dy": 6},
    ("vertical", "inside-bottom"): {"baseline": "bottom", "dy": -6},
    ("vertical", "left"): {"align": "right", "dx": -6},
    ("vertical", "right"): {"align": "left", "dx": 6},
    ("vertical", "inside-left"): {"align": "left", "dx": 6},
    ("vertical", "inside-right"): {"align": "right", "dx": -6},
    ("horizontal", "right"): {"align": "left", "dx": 6},
    ("horizontal", "left"): {"align": "right", "dx": -6},
    ("horizontal", "inside-right"): {"align": "right", "dx": -6},
    ("horizontal", "inside-left"): {"align": "left", "dx": 6},
    ("horizontal", "top"): {"baseline": "bottom", "dy": -6},
    ("horizontal", "bottom"): {"baseline": "top", "dy": 8},
    ("horizontal", "inside-top"): {"baseline": "top", "dy": 6},
    ("horizontal", "inside-bottom"): {"baseline": "bottom", "dy": -6},
}

DEFAULT_LABEL_POSITION: dict[str, str] = {
    "vertical": "inside-top",
    "horizontal": "inside-right",
}

_INSIDE_LABEL_COLOR = "#ffffff"
_OUTSIDE_LABEL_COLOR = "#333333"


def resolve_label_spec(label: LabelSpec | None) -> LabelConfig | None:
    if label is None or label is False:
        return None
    if label is True:
        return LabelConfig()
    return label


def resolve_label_cascade(
    layer_label: LabelSpec | None,
    entry_label: LabelSpec | None,
    top_label: LabelSpec | None,
) -> LabelSpec | None:
    if layer_label is not None:
        return layer_label
    if entry_label is not None:
        return entry_label
    return top_label


def detect_orientation(
    spec: ChartSpec,
    resolver: FieldTypeResolver,
) -> Literal["vertical", "horizontal"]:
    if isinstance(spec.rows, list):
        return "vertical"
    if isinstance(spec.cols, list):
        return "horizontal"
    if isinstance(spec.rows, str) and resolver.is_measure(spec.rows):
        return "vertical"
    return "horizontal"


def _strip_axis_metadata(enc: dict[str, Any]) -> dict[str, Any]:
    enc.pop("axis", None)
    enc.pop("title", None)
    return enc


def build_label_layer(
    measure_field: str,
    base_x_enc: dict[str, Any],
    base_y_enc: dict[str, Any],
    label_config: LabelConfig,
    orientation: Literal["vertical", "horizontal"],
    resolver: FieldTypeResolver,
    color_enc: dict[str, Any] | None = None,
    detail_enc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    label_field = label_config.field or measure_field

    position = label_config.position or DEFAULT_LABEL_POSITION[orientation]
    position_props = LABEL_POSITION_MAP[(orientation, position)]

    mark_props: dict[str, Any] = {"type": "text", **position_props}
    if label_config.color:
        mark_props["color"] = label_config.color
    else:
        mark_props["color"] = (
            _INSIDE_LABEL_COLOR if position.startswith("inside") else _OUTSIDE_LABEL_COLOR
        )
    if label_config.size:
        mark_props["fontSize"] = label_config.size

    encoding: dict[str, Any] = {
        "x": _strip_axis_metadata({**base_x_enc}),
        "y": _strip_axis_metadata({**base_y_enc}),
    }

    text_enc: dict[str, Any] = {
        "field": resolver.resolve_base_field(label_field),
        "type": resolver.resolve(label_field),
    }
    fmt = label_config.format or resolver.resolve_format(label_field)
    if fmt:
        text_enc["format"] = fmt
    encoding["text"] = text_enc

    details: list[dict[str, Any]] = []
    if color_enc is not None and "field" in color_enc:
        details.append({"field": color_enc["field"], "type": color_enc.get("type", "nominal")})
    if detail_enc is not None:
        details.append({**detail_enc})
    if len(details) == 1:
        encoding["detail"] = details[0]
    elif len(details) > 1:
        encoding["detail"] = details

    return {"mark": mark_props, "encoding": encoding}


def wrap_spec_with_label(
    spec_dict: dict[str, Any],
    label_layer: dict[str, Any],
) -> dict[str, Any]:
    transforms = spec_dict.pop("transform", None)
    mark_spec = {"mark": spec_dict["mark"], "encoding": spec_dict["encoding"]}
    result: dict[str, Any] = {"layer": [mark_spec, label_layer]}
    if transforms:
        result["transform"] = transforms
    return result


_BAR_MARK_TYPES = {"bar"}


def is_bar_mark(mark: MarkSpec) -> bool:
    if isinstance(mark, str):
        return mark in _BAR_MARK_TYPES
    return mark.type in _BAR_MARK_TYPES


def maybe_wrap_with_label(
    panel: dict[str, Any],
    mark: MarkSpec,
    label: LabelSpec | None,
    measure_field: str,
    orientation: Literal["vertical", "horizontal"],
    resolver: FieldTypeResolver,
) -> dict[str, Any]:
    label_config = resolve_label_spec(label)
    if label_config is None:
        return panel
    if not is_bar_mark(mark):
        return panel

    color_enc = panel["encoding"].get("color")
    detail_enc = panel["encoding"].get("detail")
    label_layer = build_label_layer(
        measure_field=measure_field,
        base_x_enc=panel["encoding"]["x"],
        base_y_enc=panel["encoding"]["y"],
        label_config=label_config,
        orientation=orientation,
        resolver=resolver,
        color_enc=color_enc,
        detail_enc=detail_enc,
    )
    return wrap_spec_with_label(panel, label_layer)
