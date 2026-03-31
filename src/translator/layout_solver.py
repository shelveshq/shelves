"""
Layout Solver

Resolves the dashboard component tree to concrete pixel dimensions.
Implements the v2 sizing model: border-box semantics, three-bucket
distribution (% → px → auto), and overconstrained handling.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from typing import Any

from src.schema.layout_schema import (
    DashboardSpec,
    resolve_child,
)

_SIZE_RE = re.compile(r"^(\d+)(px|%)?$")
_CONTAINER_TYPES = {"root", "container"}


@dataclass
class ResolvedNode:
    """Output of the layout solver for a single element."""

    name: str | None
    component: Any
    outer_width: int
    outer_height: int
    content_width: int
    content_height: int
    children: list[ResolvedNode] = field(default_factory=list)


def parse_spacing(value: int | str | None) -> tuple[int, int, int, int]:
    """Parse a DSL margin/padding value to (top, right, bottom, left) pixels.

    Supports: None → (0,0,0,0), int → all sides, "V H" → vertical/horizontal,
    "T R B L" → each side.
    """
    if value is None:
        return (0, 0, 0, 0)
    if isinstance(value, int):
        return (value, value, value, value)
    # String: split on whitespace
    parts = str(value).split()
    if len(parts) == 1:
        v = int(parts[0])
        return (v, v, v, v)
    if len(parts) == 2:
        vert, horiz = int(parts[0]), int(parts[1])
        return (vert, horiz, vert, horiz)
    if len(parts) == 4:
        return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    raise ValueError(f"Invalid spacing value: {value!r}")


def _parse_size(value: Any) -> tuple[str, int | float]:
    """Classify a size value into (bucket, numeric_value).

    Returns:
        ("pct", float_percentage) for percentage values
        ("px", int_pixels) for fixed pixel values
        ("auto", 0) for auto/omitted
    """
    if value is None or value == "auto":
        return ("auto", 0)
    if isinstance(value, int):
        return ("px", value)
    if isinstance(value, str):
        m = _SIZE_RE.match(value)
        if m:
            num = int(m.group(1))
            unit = m.group(2)
            if unit == "%":
                return ("pct", num / 100.0)
            # bare number or "Npx"
            return ("px", num)
        if value == "auto":
            return ("auto", 0)
    raise ValueError(f"Invalid size value: {value!r}")


def _resolve_children(
    children_specs: list[tuple[str | None, Any]],
    container_content_w: int,
    container_content_h: int,
    orientation: str,
    container_name: str | None,
) -> list[ResolvedNode]:
    """Resolve a list of children within a container's content box."""
    if not children_specs:
        return []

    is_horizontal = orientation == "horizontal"
    main_content = container_content_w if is_horizontal else container_content_h
    cross_content = container_content_h if is_horizontal else container_content_w

    # Step 2: Subtract all child margins on main axis
    total_margin = 0
    child_margins: list[tuple[int, int, int, int]] = []
    for _name, comp in children_specs:
        margin = parse_spacing(getattr(comp, "margin", None))
        child_margins.append(margin)
        if is_horizontal:
            total_margin += margin[1] + margin[3]  # right + left
        else:
            total_margin += margin[0] + margin[2]  # top + bottom

    distributable = max(main_content - total_margin, 0)

    # Step 3: Classify into buckets
    buckets: list[tuple[str, int | float]] = []
    for _name, comp in children_specs:
        main_size = getattr(comp, "width", None) if is_horizontal else getattr(comp, "height", None)
        buckets.append(_parse_size(main_size))

    # Step 4: Resolve sizes in priority order
    # Percentages resolve against the content box (pre-margin)
    resolved_sizes: list[int] = [0] * len(children_specs)

    # Bucket A: percentages
    pct_indices = [i for i, (b, _) in enumerate(buckets) if b == "pct"]
    px_indices = [i for i, (b, _) in enumerate(buckets) if b == "px"]
    auto_indices = [i for i, (b, _) in enumerate(buckets) if b == "auto"]

    resolved_a = 0
    for i in pct_indices:
        val = int(round(buckets[i][1] * main_content))
        resolved_sizes[i] = val
        resolved_a += val

    resolved_b = 0
    for i in px_indices:
        resolved_sizes[i] = int(buckets[i][1])
        resolved_b += resolved_sizes[i]

    total_claimed = resolved_a + resolved_b

    if total_claimed <= distributable:
        # Case 1: Everything fits
        remaining = distributable - total_claimed
        if auto_indices:
            base = remaining // len(auto_indices)
            leftover = remaining - base * len(auto_indices)
            for idx, i in enumerate(auto_indices):
                resolved_sizes[i] = base + (1 if idx < leftover else 0)
        # else: remaining space is empty (start-aligned packing)

        # Warn if auto children get 0
        if auto_indices and remaining == 0:
            for i in auto_indices:
                child_name = children_specs[i][0] or f"child[{i}]"
                cname = container_name or "root"
                warnings.warn(
                    f"Auto-sized child `{child_name}` in `{cname}` received 0px on main axis; "
                    f"container is fully claimed by explicit sizes"
                )
    else:
        # Case 2: Overconstrained
        if resolved_a <= distributable:
            # Percentages fit; shrink fixed proportionally
            remaining_for_fixed = distributable - resolved_a
            if resolved_b > 0:
                cname = container_name or "root"
                warnings.warn(
                    f"Children in `{cname}` exceed available space by "
                    f"{total_claimed - distributable}px; fixed sizes reduced proportionally"
                )
                for i in px_indices:
                    resolved_sizes[i] = int(
                        round(resolved_sizes[i] / resolved_b * remaining_for_fixed)
                    )
                # Fix rounding
                actual_fixed = sum(resolved_sizes[i] for i in px_indices)
                if px_indices and actual_fixed != remaining_for_fixed:
                    resolved_sizes[px_indices[0]] += remaining_for_fixed - actual_fixed
            # Auto children get 0
            for i in auto_indices:
                resolved_sizes[i] = 0
                child_name = children_specs[i][0] or f"child[{i}]"
                cname = container_name or "root"
                warnings.warn(
                    f"Auto-sized child `{child_name}` in `{cname}` received 0px on main axis; "
                    f"container is fully claimed by explicit sizes"
                )
        else:
            # Even percentages exceed space — shrink all proportionally
            cname = container_name or "root"
            total_pct = sum(buckets[i][1] for i in pct_indices) * 100
            warnings.warn(
                f"Percentage allocations in `{cname}` total {total_pct:.0f}% and exceed "
                f"available space; all sizes reduced proportionally"
            )
            total_resolved = resolved_a + resolved_b + sum(resolved_sizes[i] for i in auto_indices)
            if total_resolved > 0:
                for i in range(len(resolved_sizes)):
                    resolved_sizes[i] = int(
                        round(resolved_sizes[i] / total_resolved * distributable)
                    )
            # Fix rounding
            actual_total = sum(resolved_sizes)
            if actual_total != distributable and resolved_sizes:
                resolved_sizes[0] += distributable - actual_total

    # Step 5: Cross-axis resolution + Step 6: Content areas + Step 7: Recurse
    result: list[ResolvedNode] = []
    for idx, (child_name, comp) in enumerate(children_specs):
        main_size = resolved_sizes[idx]
        margin = child_margins[idx]

        # Cross-axis
        cross_size_val = (
            getattr(comp, "height", None) if is_horizontal else getattr(comp, "width", None)
        )
        cross_bucket, cross_num = _parse_size(cross_size_val)
        if cross_bucket == "px":
            cross_size = int(cross_num)
        elif cross_bucket == "pct":
            cross_size = int(round(cross_num * cross_content))
        else:
            # Default: 100% of container cross-axis content
            # Subtract cross-axis margins
            if is_horizontal:
                cross_margins = margin[0] + margin[2]  # top + bottom
            else:
                cross_margins = margin[1] + margin[3]  # left + right
            cross_size = max(cross_content - cross_margins, 0)

        if is_horizontal:
            outer_w, outer_h = main_size, cross_size
        else:
            outer_w, outer_h = cross_size, main_size

        # Content area = outer - padding
        padding = parse_spacing(getattr(comp, "padding", None))
        content_w = outer_w - padding[1] - padding[3]
        content_h = outer_h - padding[0] - padding[2]

        # Clamp negative content areas
        if content_w < 0 or content_h < 0:
            cname = child_name or f"child[{idx}]"
            pad_total = (padding[0] + padding[2], padding[1] + padding[3])
            size_val = outer_w if content_w < 0 else outer_h
            pad_val = pad_total[1] if content_w < 0 else pad_total[0]
            warnings.warn(
                f"Padding on `{cname}` ({pad_val}px) exceeds its solved size ({size_val}px); "
                f"content area clamped to 0"
            )
            content_w = max(content_w, 0)
            content_h = max(content_h, 0)

        # Recurse for containers
        children: list[ResolvedNode] = []
        comp_type = getattr(comp, "type", None)
        if comp_type in _CONTAINER_TYPES:
            child_orientation = getattr(comp, "orientation", "horizontal")
            components_dict = {}
            child_specs = []
            for raw_child in getattr(comp, "contains", []):
                resolved_name, resolved_comp = resolve_child(raw_child, components_dict)
                child_specs.append((resolved_name, resolved_comp))
            children = _resolve_children(
                child_specs, content_w, content_h, child_orientation, child_name
            )

        result.append(
            ResolvedNode(
                name=child_name,
                component=comp,
                outer_width=outer_w,
                outer_height=outer_h,
                content_width=content_w,
                content_height=content_h,
                children=children,
            )
        )

    return result


def solve_layout(dashboard: DashboardSpec) -> ResolvedNode:
    """Solve the layout tree, producing a ResolvedNode with pixel dimensions."""
    root = dashboard.root
    canvas = dashboard.canvas
    components_dict = dashboard.components or {}

    # Root resolution
    root_margin = parse_spacing(root.margin)
    root_outer_w = canvas.width - root_margin[1] - root_margin[3]
    root_outer_h = canvas.height - root_margin[0] - root_margin[2]

    root_padding = parse_spacing(root.padding)
    root_content_w = max(root_outer_w - root_padding[1] - root_padding[3], 0)
    root_content_h = max(root_outer_h - root_padding[0] - root_padding[2], 0)

    # Resolve root children
    child_specs: list[tuple[str | None, Any]] = []
    for raw_child in root.contains:
        name, comp = resolve_child(raw_child, components_dict)
        child_specs.append((name, comp))

    children = _resolve_children(
        child_specs, root_content_w, root_content_h, root.orientation, None
    )

    return ResolvedNode(
        name=None,
        component=root,
        outer_width=root_outer_w,
        outer_height=root_outer_h,
        content_width=root_content_w,
        content_height=root_content_h,
        children=children,
    )
