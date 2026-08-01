"""
Layout Flatten Phase

Resolves all styles and component references into a single concrete tree
before the solver and renderer consume it. Mental model: "compile everything
flat before any downstream processing" — like dbt's Jinja compilation.

Public API: flatten_dashboard(spec) -> FlatNode
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Literal

from shelves.schema.layout_schema import (
    Canvas,
    Component,
    ContainerComponent,
    ControlComponent,
    DashboardSpec,
    LegendComponent,
    RootComponent,
    SheetComponent,
    StyleProperties,
    resolve_child,
)


@dataclass
class PropertyOrigin:
    """Tracks where a resolved property value came from."""

    value: Any
    source: Literal["style", "inline", "default"]
    style_name: str | None = None  # only set when source="style"


@dataclass
class FlatNode:
    """A fully-resolved node in the flattened tree. No indirection."""

    name: str | None
    component: Component | RootComponent
    children: list[FlatNode]
    origins: dict[str, PropertyOrigin]
    canvas: Canvas | None = field(default=None)  # only present on the root node
    # SHE-29: the single source of truth for this node's DOM identity. Assigned
    # once by `_assign_dom_ids` for sheets and legends (the explicit `name`, or
    # `auto-N` for anonymous nodes); None for every other node type. The renderer
    # prefixes it (`sheet-<dom_id>` / `legend-<dom_id>`); discovery and the
    # embedded-spec keys use it directly. Computed in exactly one place so the
    # DOM id and its spec key can never desync.
    dom_id: str | None = field(default=None)


def _merge_style_onto_component(
    comp: Any,
    style_props: StyleProperties,
    style_name: str,
) -> tuple[Any, dict[str, PropertyOrigin]]:
    """Merge a style's properties onto a component. Inline values win.

    Returns (new_component, origins_dict). Always copies — never mutates.

    Algorithm per property:
    - If only style has it: copy to component, origin = "style"
    - If both have it: warn, keep inline, origin = "inline"
    - If only inline has it: keep as-is, origin = "inline"
    """
    origins: dict[str, PropertyOrigin] = {}
    updates: dict[str, Any] = {}

    comp_model_fields = set(type(comp).model_fields.keys())

    for field_name in type(style_props).model_fields:
        style_val = getattr(style_props, field_name)
        if style_val is None:
            continue

        # Determine inline value: model field or pydantic extra
        if field_name in comp_model_fields:
            inline_val = getattr(comp, field_name, None)
        else:
            extras = getattr(comp, "__pydantic_extra__", None) or {}
            inline_val = extras.get(field_name)

        if inline_val is not None:
            # Both defined — inline wins, warn
            warnings.warn(
                f"Property '{field_name}' on component overrides style '{style_name}' "
                f"(inline: {inline_val!r}, style: {style_val!r}). Inline value used.",
                stacklevel=4,
            )
            origins[field_name] = PropertyOrigin(value=inline_val, source="inline")
        else:
            # Only style has it — apply
            updates[field_name] = style_val
            origins[field_name] = PropertyOrigin(
                value=style_val, source="style", style_name=style_name
            )

    new_comp = comp.model_copy(update=updates)
    return new_comp, origins


def _flatten_children(
    contains: list[Any],
    components: dict[str, Any],
    styles: dict[str, StyleProperties],
) -> list[FlatNode]:
    """Recursively flatten a contains list into FlatNodes."""
    result = []
    for entry in contains:
        name, comp = resolve_child(entry, components)

        # Always copy to ensure each usage site is independent
        comp = comp.model_copy()

        # Merge style if referenced
        origins: dict[str, PropertyOrigin] = {}
        if comp.style and comp.style in styles:
            comp, origins = _merge_style_onto_component(comp, styles[comp.style], comp.style)

        # Recurse into containers
        children: list[FlatNode] = []
        if isinstance(comp, ContainerComponent) and comp.contains:
            children = _flatten_children(comp.contains, components, styles)

        result.append(FlatNode(name=name, component=comp, children=children, origins=origins))

    return result


def _assign_dom_ids(root: FlatNode) -> None:
    """Assign `dom_id` to every sheet, legend, and control node in pre-order.

    Counters are independent per type so a legend never offsets a sheet's id.
    """
    sheet_counter = 0
    legend_counter = 0
    control_counter = 0

    def walk(node: FlatNode) -> None:
        nonlocal sheet_counter, legend_counter, control_counter
        comp = node.component
        if isinstance(comp, SheetComponent):
            if node.name is not None:
                node.dom_id = node.name
            else:
                sheet_counter += 1
                node.dom_id = f"auto-{sheet_counter}"
        elif isinstance(comp, LegendComponent):
            if node.name is not None:
                node.dom_id = node.name
            else:
                legend_counter += 1
                node.dom_id = f"auto-{legend_counter}"
        elif isinstance(comp, ControlComponent):
            if node.name is not None:
                node.dom_id = node.name
            else:
                control_counter += 1
                node.dom_id = f"auto-{control_counter}"
        for child in node.children:
            walk(child)

    walk(root)


def flatten_dashboard(spec: DashboardSpec) -> FlatNode:
    """Flatten a DashboardSpec into a fully-resolved tree.

    Every node in the returned tree has concrete padding/margin/style values
    with no remaining style refs to resolve. The solver and renderer consume
    this tree as the single source of truth.
    """
    styles = spec.styles or {}
    components = spec.components or {}

    # Handle root's own style
    root: RootComponent = spec.root.model_copy()
    root_origins: dict[str, PropertyOrigin] = {}
    if root.style and root.style in styles:
        root, root_origins = _merge_style_onto_component(root, styles[root.style], root.style)

    # Walk root.contains
    root_children = _flatten_children(root.contains, components, styles)

    root_node = FlatNode(
        name=None,
        component=root,
        children=root_children,
        origins=root_origins,
        canvas=spec.canvas,
    )
    # SHE-29: stamp DOM ids once, here, so every consumer (sheet discovery,
    # legend discovery, the solver, the renderer) reads the same stored value.
    _assign_dom_ids(root_node)
    return root_node
