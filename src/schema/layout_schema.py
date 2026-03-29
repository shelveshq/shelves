"""
Layout DSL Schema

Pydantic models for the Layout DSL: DashboardSpec, component models,
resolve_child(), parse_dashboard(), load_dashboard().

This is the schema layer for dashboard definitions — the equivalent of
chart_schema.py for the Chart DSL. It handles YAML parsing, validation,
and typed Python objects for every component in a dashboard definition.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─── Size Type ─────────────────────────────────────────────────────

SizeValue = Union[int, str, None]

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
    opacity: float | None = Field(None, ge=0.0, le=1.0)
    font_size: int | None = None
    font_weight: str | int | None = None
    font_family: str | None = None
    color: str | None = None
    text_align: Literal["left", "center", "right"] | None = None


# ─── Canvas ────────────────────────────────────────────────────────


class Canvas(BaseModel):
    width: int = 1440
    height: int = 900


# ─── Component Models ─────────────────────────────────────────────


class ContainerBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    orientation: Literal["horizontal", "vertical"]
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None
    align: Literal["start", "center", "end", "stretch"] | None = None
    justify: Literal["start", "center", "end", "between", "around", "evenly"] | None = None
    contains: list[Any] = Field(default_factory=list)


class RootComponent(ContainerBase):
    type: Literal["root"]


class ContainerComponent(ContainerBase):
    type: Literal["container"]


class SheetComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["sheet"]
    link: str
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class TextComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["text"]
    content: str
    preset: Literal["title", "subtitle", "heading", "body", "caption", "label"] | None = None
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class NavigationBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str
    link: str
    target: Literal["_self", "_blank"] = "_self"
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class NavigationComponent(NavigationBase):
    type: Literal["navigation"]


class NavigationButtonComponent(NavigationBase):
    type: Literal["navigation_button"]


class NavigationLinkComponent(NavigationBase):
    type: Literal["navigation_link"]


class ImageComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["image"]
    src: str
    alt: str = ""
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


class BlankComponent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["blank"]
    width: SizeValue = None
    height: SizeValue = None
    margin: int | str | None = None
    padding: int | str | None = None
    style: str | None = None
    html: str | None = None


# ─── Component Union ──────────────────────────────────────────────

Component = Union[
    RootComponent,
    ContainerComponent,
    SheetComponent,
    TextComponent,
    NavigationComponent,
    NavigationButtonComponent,
    NavigationLinkComponent,
    ImageComponent,
    BlankComponent,
]

# ─── Type Discriminator Map ───────────────────────────────────────

_TYPE_MAP: dict[str, type[BaseModel]] = {
    "root": RootComponent,
    "container": ContainerComponent,
    "sheet": SheetComponent,
    "text": TextComponent,
    "navigation": NavigationComponent,
    "navigation_button": NavigationButtonComponent,
    "navigation_link": NavigationLinkComponent,
    "image": ImageComponent,
    "blank": BlankComponent,
}

_CONTAINER_TYPES = {"root", "container"}


# ─── Component Parsing ────────────────────────────────────────────


def _parse_component(data: dict) -> Component:
    """Parse a raw dict into the correct Component subclass.

    Uses the 'type' field as a discriminator to select the right model.
    """
    comp_type = data.get("type")
    if comp_type not in _TYPE_MAP:
        raise ValueError(f"Unknown component type: {comp_type!r}. Valid types: {list(_TYPE_MAP)}")
    return _TYPE_MAP[comp_type](**data)


# ─── Child Resolution ─────────────────────────────────────────────


def resolve_child(
    node: Any,
    components: dict[str, Component],
) -> tuple[str | None, Component]:
    """Resolve a contains list entry to (name, component).

    Three shapes:
    1. String reference: "kpi_revenue" -> lookup in components dict
    2. Inline anonymous: {"type": "blank", "width": 10} -> parse directly
    3. Inline named: {"revenue_chart": {"type": "sheet", ...}} -> parse inner dict

    Returns:
        (name, component) -- name is None for anonymous components.

    Raises:
        KeyError: if string ref not found in components
        ValueError: if dict doesn't match any known shape or type is invalid
    """
    # Shape 1: string reference
    if isinstance(node, str):
        return (node, components[node])

    # Shape 2: inline anonymous (dict with "type" key)
    if isinstance(node, dict) and "type" in node:
        return (None, _parse_component(node))

    # Shape 3: inline named (single-key dict wrapping a component dict)
    if isinstance(node, dict) and len(node) == 1:
        name = next(iter(node))
        return (name, _parse_component(node[name]))

    raise ValueError(f"Cannot resolve child: {node!r}")


# ─── Dashboard Spec ───────────────────────────────────────────────


class DashboardSpec(BaseModel):
    dashboard: str
    description: str | None = None
    canvas: Canvas = Field(default_factory=Canvas)
    styles: dict[str, StyleProperties] | None = None
    components: dict[str, Any] | None = None
    root: RootComponent

    @model_validator(mode="before")
    @classmethod
    def _parse_components(cls, data: Any) -> Any:
        """Parse the components dict values into Component objects."""
        if isinstance(data, dict) and "components" in data and data["components"]:
            parsed = {}
            for name, comp_data in data["components"].items():
                if isinstance(comp_data, dict):
                    parsed[name] = _parse_component(comp_data)
                else:
                    parsed[name] = comp_data
            data["components"] = parsed
        return data

    @model_validator(mode="after")
    def _validate_tree(self) -> DashboardSpec:
        """Walk all components and validate constraints."""
        styles_dict = self.styles or {}
        components_dict = self.components or {}

        def _validate_node(node: Any) -> None:
            """Validate a single node (Component or raw dict/string)."""
            # For raw contains entries, resolve them first
            if isinstance(node, str):
                # String ref — validate it exists in components
                if node not in components_dict:
                    raise ValueError(f"String ref {node!r} not found in components")
                _validate_node(components_dict[node])
                return

            if isinstance(node, dict):
                # Raw dict from contains — resolve to component for validation
                if "type" in node:
                    comp = _parse_component(node)
                    _validate_node(comp)
                elif len(node) == 1:
                    name = next(iter(node))
                    comp = _parse_component(node[name])
                    _validate_node(comp)
                return

            # Component object — validate fields
            # Check style ref
            style = getattr(node, "style", None)
            if style is not None and style not in styles_dict:
                raise ValueError(f"Style {style!r} not found in styles block")

            # Check size values
            for attr in ("width", "height"):
                val = getattr(node, attr, None)
                if not _is_valid_size(val):
                    raise ValueError(f"Invalid size value for {attr}: {val!r}")

            # Check leaf types don't have contains
            comp_type = getattr(node, "type", None)
            if comp_type not in _CONTAINER_TYPES:
                extra = getattr(node, "__pydantic_extra__", None) or {}
                if "contains" in extra:
                    raise ValueError(f"Leaf component type {comp_type!r} cannot have contains")

            # Recurse into contains for container types
            if comp_type in _CONTAINER_TYPES:
                for child in getattr(node, "contains", []):
                    _validate_node(child)

        # Validate the root tree
        _validate_node(self.root)

        # Validate pre-defined components
        for comp in components_dict.values():
            _validate_node(comp)

        return self


# ─── Public API ───────────────────────────────────────────────────


def parse_dashboard(yaml_string: str) -> DashboardSpec:
    """Parse a YAML string and validate against the Layout DSL schema."""
    raw = yaml.safe_load(yaml_string)
    return DashboardSpec.model_validate(raw)


def load_dashboard(path: Path) -> DashboardSpec:
    """Load and validate a dashboard YAML file."""
    return parse_dashboard(path.read_text())
