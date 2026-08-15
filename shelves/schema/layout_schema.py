"""
Layout DSL Schema — Type-Led Syntax

Pydantic models for the Layout DSL where every element starts with its type
as the YAML key. Components are bare-string references to predefined entries.

Public API: parse_dashboard(), load_dashboard(), resolve_child()
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from shelves.params.substitute import ParameterReferenceError, ParameterSet, substitute_parameters

# ─── Size Type ─────────────────────────────────────────────────────

SizeValue = int | str | None

_SIZE_RE = re.compile(r"^(\d+)(px|%)?$")


def _is_valid_size(value: SizeValue) -> bool:
    """Check if a size value is valid.

    Valid: None, int, "auto", "Npx", "N%", "N" (bare number string).
    """
    if value is None:
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        if value == "auto":
            return True
        return bool(_SIZE_RE.match(value))
    return False


# ─── Style Properties ─────────────────────────────────────────────


class StyleProperties(BaseModel):
    """Reusable style preset. All properties optional."""

    background: str | None = None
    border: str | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    border_radius: int | str | None = None
    shadow: str | None = None
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    font_size: int | None = None
    font_weight: str | int | None = None
    font_family: str | None = None
    color: str | None = None
    text_align: Literal["left", "center", "right"] | None = None
    padding: int | str | None = None
    margin: int | str | None = None


# ─── Canvas ────────────────────────────────────────────────────────


class Canvas(BaseModel):
    width: int = 1440
    height: int = 900


# ─── Type Constants ───────────────────────────────────────────────

KNOWN_LEAF_TYPES = {
    "sheet",
    "text",
    "image",
    "button",
    "link",
    "blank",
    "legend",
    "parameter",
    "filter",
}
KNOWN_CONTAINER_TYPES = {"horizontal", "vertical"}
KNOWN_TYPES = KNOWN_LEAF_TYPES | KNOWN_CONTAINER_TYPES

VALID_PRESETS = {"title", "subtitle", "heading", "body", "caption", "label"}
VALID_FIT = {"width", "height", "fill"}


# ─── Component Models ─────────────────────────────────────────────


class SheetComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["sheet"] = "sheet"
    link: str
    fit: Literal["width", "height", "fill"] | None = None
    show_title: bool = True
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class TextComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["text"] = "text"
    content: str
    preset: Literal["title", "subtitle", "heading", "body", "caption", "label"] | None = None
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class ImageComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["image"] = "image"
    src: str
    alt: str = ""
    # True: scale to fit box (object-fit: contain). False: natural size, box scrolls.
    fit: bool = True
    # True: center in box. False: top-left. Only applies when fit=True.
    center: bool = False
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class LegendComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["legend"] = "legend"
    source: str  # chart YAML path the legend draws from (matches a sheet's `link`)
    field: str  # field name whose scale the legend will render (resolved in SHE-10)
    title: str | None = None
    orientation: Literal["vertical", "horizontal"] = "vertical"
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class ButtonComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["button"] = "button"
    text: str
    href: str
    target: Literal["_self", "_blank"] = "_self"
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class LinkComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["link"] = "link"
    text: str
    href: str
    target: Literal["_self", "_blank"] = "_self"
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class BlankComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["blank"] = "blank"
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class ParameterComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["parameter"] = "parameter"
    param: str = Field(min_length=1)
    label: str | None = None
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


FilterMode = Literal[
    "multi",
    "single",
    "wildcard",
    "range",
    "at_least",
    "at_most",
    "after",
    "before",
]


class FilterComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["filter"] = "filter"
    field: str = Field(min_length=1)
    model: str = Field(min_length=1)
    targets: list[str] | Literal["all"] = "all"
    mode: FilterMode | None = None
    default: Any = None
    label: str | None = None
    # For `single`/`multi` (dimension) modes only: True (default) renders a
    # compact dropdown widget; False renders a top-aligned, scrollable open
    # list. Ignored for other modes. (SHE-8x)
    dropdown: bool = True
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class ContainerComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["horizontal", "vertical"]
    contains: list[Any] = Field(default_factory=list)
    gap: int = 0
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_contains(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("contains") is None:
            data["contains"] = []
        return data


class RootComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    orientation: Literal["horizontal", "vertical"]
    contains: list[Any] = Field(default_factory=list)
    gap: int = 0
    padding: int | str | None = None
    margin: int | str | None = None
    style: str | None = None
    html: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_contains(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("contains") is None:
            data["contains"] = []
        return data


# ─── Component Union ──────────────────────────────────────────────

Component = (
    ContainerComponent
    | SheetComponent
    | TextComponent
    | ButtonComponent
    | LinkComponent
    | ImageComponent
    | BlankComponent
    | LegendComponent
    | ParameterComponent
    | FilterComponent
)


# ─── Leaf Type Builders ──────────────────────────────────────────

_LEAF_BUILDERS: dict[str, tuple[type, str]] = {
    # type_key → (ModelClass, primary_field_name)
    "sheet": (SheetComponent, "link"),
    "text": (TextComponent, "content"),
    "image": (ImageComponent, "src"),
    "button": (ButtonComponent, "text"),
    "link": (LinkComponent, "text"),
    "blank": (BlankComponent, ""),  # blank has no primary field
    "legend": (LegendComponent, "source"),
    "parameter": (ParameterComponent, "param"),
    "filter": (FilterComponent, "field"),
}


# ─── Child Resolution ─────────────────────────────────────────────


def resolve_child(
    node: Any,
    components: dict[str, Any],
) -> tuple[str | None, Component]:
    """Resolve a contains list entry to (name, component).

    Type-led syntax shapes:
    1. String reference: "kpi_revenue" → lookup in components dict
    2. Leaf type (multi-key dict): {sheet: "foo.yaml", style: "card"} → SheetComponent
    3. Container type (single-key dict): {horizontal: {gap: 16, contains: [...]}}

    Returns:
        (name, component) — name is None for anonymous components.

    Raises:
        KeyError: if string ref not found in components
        ValueError: if dict doesn't match any known shape
    """
    # Shape 1: string reference
    if isinstance(node, str):
        if node not in components:
            raise KeyError(f"Component {node!r} not found in components")
        return (node, components[node])

    if not isinstance(node, dict):
        raise ValueError(f"Cannot resolve child: {node!r}")

    # Find which known type keys are present
    type_keys = set(node.keys()) & KNOWN_TYPES

    if not type_keys:
        raise ValueError(f"No known type key found in {node!r}. Known types: {sorted(KNOWN_TYPES)}")

    if len(type_keys) > 1:
        raise ValueError(
            f"Multiple known type keys found in {node!r}: {sorted(type_keys)}. "
            "Exactly one known type key is required."
        )

    type_key = next(iter(type_keys))

    # Shape 2: Leaf type (multi-key dict)
    if type_key in KNOWN_LEAF_TYPES:
        primary_value = node[type_key]
        props = {k: v for k, v in node.items() if k != type_key}

        # Extract name (only sheets use it for IDs)
        name = props.pop("name", None)

        # Validate: leaf types cannot have contains
        if "contains" in props:
            raise ValueError(f"Leaf type {type_key!r} cannot have 'contains'")

        # Build the model
        model_cls, primary_field = _LEAF_BUILDERS[type_key]
        if primary_field:
            comp = model_cls(**{primary_field: primary_value, **props})
        else:
            # blank: no primary field
            comp = model_cls(**props)

        return (name, comp)

    # Shape 3: Container type (single-key dict, value is properties dict)
    if type_key in KNOWN_CONTAINER_TYPES:
        inner = node[type_key]
        if not isinstance(inner, dict):
            inner = {}
        comp = ContainerComponent(type=type_key, **inner)
        return (None, comp)

    raise ValueError(f"Cannot resolve child: {node!r}")


def _resolve_component_def(
    name: str,
    raw: Any,
    all_component_names: set[str],
) -> Component:
    """Parse a single component definition from the components block.

    Uses the same type-led syntax as resolve_child, but additionally
    validates that container components don't reference other components.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"Component {name!r} must be a dict, got {type(raw).__name__}")

    _, comp = resolve_child(raw, {})

    # Validate: container components cannot reference other component names
    if isinstance(comp, ContainerComponent):
        _validate_no_component_refs(comp.contains, all_component_names, name)

    return comp


def _validate_no_component_refs(
    contains: list[Any],
    component_names: set[str],
    parent_name: str,
) -> None:
    """Ensure a contains list has no bare-string references to components."""
    for entry in contains:
        if isinstance(entry, str) and entry in component_names:
            raise ValueError(
                f"Component {parent_name!r} references component {entry!r}. "
                f"Components cannot reference other components."
            )
        # Recurse into nested containers
        if isinstance(entry, dict):
            type_keys = set(entry.keys()) & KNOWN_CONTAINER_TYPES
            if type_keys:
                type_key = type_keys.pop()
                inner = entry[type_key]
                if isinstance(inner, dict) and "contains" in inner:
                    _validate_no_component_refs(inner["contains"], component_names, parent_name)


# ─── Dashboard Spec ───────────────────────────────────────────────


class DashboardSpec(BaseModel):
    dashboard: str
    description: str | None = None
    canvas: Canvas = Field(default_factory=Canvas)
    styles: dict[str, StyleProperties] | None = None
    components: dict[str, Any] | None = None
    root: Any  # Parsed to RootComponent in validator

    @model_validator(mode="before")
    @classmethod
    def _parse_raw(cls, data: Any) -> Any:
        """Pre-process raw YAML data before Pydantic validation."""
        if not isinstance(data, dict):
            raise ValueError("Dashboard must be a dict")

        # Validate required fields
        if "dashboard" not in data:
            raise ValueError("Missing required field: 'dashboard'")
        if "root" not in data:
            raise ValueError("Missing required field: 'root'")

        # SHE-89: parameters are a project-level entity, not dashboard DSL.
        # Reject before the in-place mutations below so the message is clear.
        if "parameters" in data:
            raise ValueError(
                "'parameters' is not a dashboard property — parameters are "
                "declared once for the project in models/parameters.yaml and "
                "referenced here with $name."
            )

        root_data = data.get("root", {})
        if not isinstance(root_data, dict):
            raise ValueError("'root' must be a dict")
        if "orientation" not in root_data:
            raise ValueError("Root must have 'orientation'")
        if "contains" not in root_data:
            raise ValueError("Root must have 'contains'")

        # Parse components block
        raw_components = data.get("components") or {}
        if raw_components:
            component_names = set(raw_components.keys())

            # Validate: component names don't shadow known types
            shadowed = component_names & KNOWN_TYPES
            if shadowed:
                raise ValueError(f"Component names shadow known types: {sorted(shadowed)}")

            parsed = {}
            for comp_name, comp_data in raw_components.items():
                parsed[comp_name] = _resolve_component_def(comp_name, comp_data, component_names)
            data["components"] = parsed

        # Parse root
        data["root"] = RootComponent(**root_data)

        return data

    @model_validator(mode="after")
    def _validate_tree(self) -> DashboardSpec:
        """Walk all components and validate constraints."""
        styles_dict = self.styles or {}
        components_dict = self.components or {}

        def _validate_node(node: Any, check_style_refs: bool = True) -> None:
            if isinstance(node, str):
                if node not in components_dict:
                    raise ValueError(f"String ref {node!r} not found in components")
                return

            if isinstance(node, dict):
                # Raw dict in contains — resolve and validate
                _, comp = resolve_child(node, components_dict)
                _validate_node(comp, check_style_refs)
                return

            # Component object — validate fields
            if check_style_refs:
                style = getattr(node, "style", None)
                if style is not None and style not in styles_dict:
                    raise ValueError(f"Style {style!r} not found in styles block")

            for attr in ("width", "height"):
                val = getattr(node, attr, None)
                if not _is_valid_size(val):
                    raise ValueError(f"Invalid size value for {attr}: {val!r}")

            # Recurse into contains for containers and root
            contains = getattr(node, "contains", None)
            if contains is not None:
                for child in contains:
                    _validate_node(child, check_style_refs)

        # Validate the root tree (style refs checked)
        for child in self.root.contains:
            _validate_node(child, check_style_refs=True)

        # Validate pre-defined components (style refs NOT checked —
        # components may reference styles defined in other dashboards)
        for comp in components_dict.values():
            _validate_node(comp, check_style_refs=False)

        return self


# ─── Public API ───────────────────────────────────────────────────


def parse_dashboard(
    yaml_string: str,
    *,
    parameters: ParameterSet | None = None,
) -> DashboardSpec:
    """Parse a YAML string and validate against the Layout DSL schema.

    `${name}` references in text components are substituted before validation
    using `parameters` (SHE-96). None means `ParameterSet.empty()`.
    """
    raw = yaml.safe_load(yaml_string)
    if not isinstance(raw, dict):
        return DashboardSpec.model_validate(raw)

    result = substitute_parameters(raw, parameters or ParameterSet.empty())
    if result.errors:
        raise ParameterReferenceError(result.errors)

    return DashboardSpec.model_validate(result.data)


def load_dashboard(
    path: Path,
    *,
    parameters: ParameterSet | None = None,
) -> DashboardSpec:
    """Load and validate a dashboard YAML file."""
    return parse_dashboard(path.read_text(), parameters=parameters)
