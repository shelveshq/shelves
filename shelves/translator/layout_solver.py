"""
Layout Solver

Resolves the dashboard component tree to concrete pixel dimensions.
Implements the v2 sizing model: border-box semantics, three-bucket
distribution (% → px → auto), gap subtraction, and overconstrained handling.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from typing import Any

from shelves.schema.layout_schema import Component, ContainerComponent, RootComponent
from shelves.translator.layout_flatten import FlatNode

_SIZE_RE = re.compile(r"^(\d+)(px|%)?$")


@dataclass
class ResolvedNode:
    """Output of the layout solver for a single element."""

    name: str | None
    component: Component | RootComponent
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


@dataclass
class _SizeClassification:
    """Result of classifying children's sizes into buckets."""

    buckets: list[tuple[str, int | float]]
    pct_indices: list[int]
    px_indices: list[int]
    auto_indices: list[int]
    child_margins: list[tuple[int, int, int, int]]
    total_margin: int
    distributable: int


def _classify_sizes(
    flat_children: list[FlatNode],
    main_content: int,
    is_horizontal: bool,
    gap: int,
    container_name: str | None,
) -> _SizeClassification:
    """Bucket children into pct/px/auto, compute margins, and distributable space."""
    total_gap = gap * max(len(flat_children) - 1, 0)

    total_margin = 0
    child_margins: list[tuple[int, int, int, int]] = []
    for flat_child in flat_children:
        comp = flat_child.component
        margin = parse_spacing(getattr(comp, "margin", None))
        child_margins.append(margin)
        if is_horizontal:
            total_margin += margin[1] + margin[3]
        else:
            total_margin += margin[0] + margin[2]

    if total_gap > main_content - total_margin:
        cname = container_name or "root"
        warnings.warn(
            f"Gap in `{cname}` ({gap}px × {max(len(flat_children) - 1, 0)}"
            f" = {total_gap}px) exceeds available space"
            f" ({max(main_content - total_margin, 0)}px);"
            f" children will receive 0px on main axis",
            stacklevel=2,
        )

    distributable = max(main_content - total_margin - total_gap, 0)

    buckets: list[tuple[str, int | float]] = []
    for flat_child in flat_children:
        comp = flat_child.component
        sz = getattr(comp, "width", None) if is_horizontal else getattr(comp, "height", None)
        buckets.append(_parse_size(sz))

    pct_indices = [i for i, (b, _) in enumerate(buckets) if b == "pct"]
    px_indices = [i for i, (b, _) in enumerate(buckets) if b == "px"]
    auto_indices = [i for i, (b, _) in enumerate(buckets) if b == "auto"]

    return _SizeClassification(
        buckets=buckets,
        pct_indices=pct_indices,
        px_indices=px_indices,
        auto_indices=auto_indices,
        child_margins=child_margins,
        total_margin=total_margin,
        distributable=distributable,
    )


def _resolve_underconstrained(
    cls: _SizeClassification,
    resolved_sizes: list[int],
    container_name: str | None,
    flat_children: list[FlatNode],
) -> None:
    """Resolve sizes when total claimed <= distributable (happy path)."""
    remaining = cls.distributable - sum(resolved_sizes[i] for i in cls.pct_indices + cls.px_indices)
    if cls.auto_indices:
        base = remaining // len(cls.auto_indices)
        leftover = remaining - base * len(cls.auto_indices)
        for idx, i in enumerate(cls.auto_indices):
            resolved_sizes[i] = base + (1 if idx < leftover else 0)

    if cls.auto_indices and remaining == 0:
        for i in cls.auto_indices:
            child_name = flat_children[i].name or f"child[{i}]"
            cname = container_name or "root"
            warnings.warn(
                f"Auto-sized child `{child_name}` in `{cname}`"
                f" received 0px on main axis;"
                f" container is fully claimed by explicit sizes",
                stacklevel=2,
            )


def _resolve_overconstrained_proportional(
    cls: _SizeClassification,
    resolved_sizes: list[int],
    resolved_a: int,
    resolved_b: int,
    container_name: str | None,
    flat_children: list[FlatNode],
) -> None:
    """Resolve sizes when pct fits but pct+px exceeds distributable."""
    remaining_for_fixed = cls.distributable - resolved_a
    if resolved_b > 0:
        cname = container_name or "root"
        total_claimed = resolved_a + resolved_b
        warnings.warn(
            f"Children in `{cname}` exceed available space by "
            f"{total_claimed - cls.distributable}px;"
            f" fixed sizes reduced proportionally",
            stacklevel=2,
        )
        for i in cls.px_indices:
            resolved_sizes[i] = int(  # noqa: RUF046
                round(resolved_sizes[i] / resolved_b * remaining_for_fixed)
            )
        actual_fixed = sum(resolved_sizes[i] for i in cls.px_indices)
        if cls.px_indices and actual_fixed != remaining_for_fixed:
            resolved_sizes[cls.px_indices[0]] += remaining_for_fixed - actual_fixed

    for i in cls.auto_indices:
        resolved_sizes[i] = 0
        child_name = flat_children[i].name or f"child[{i}]"
        cname = container_name or "root"
        warnings.warn(
            f"Auto-sized child `{child_name}` in `{cname}`"
            f" received 0px on main axis;"
            f" container is fully claimed by explicit sizes",
            stacklevel=2,
        )


def _resolve_overconstrained_full(
    cls: _SizeClassification,
    resolved_sizes: list[int],
    resolved_a: int,
    resolved_b: int,
    container_name: str | None,
) -> None:
    """Resolve sizes when even percentages exceed distributable."""
    cname = container_name or "root"
    total_pct = sum(cls.buckets[i][1] for i in cls.pct_indices) * 100
    warnings.warn(
        f"Percentage allocations in `{cname}` total {total_pct:.0f}%"
        f" and exceed available space;"
        f" all sizes reduced proportionally",
        stacklevel=2,
    )
    total_resolved = resolved_a + resolved_b + sum(resolved_sizes[i] for i in cls.auto_indices)
    if total_resolved > 0:
        for i in range(len(resolved_sizes)):
            resolved_sizes[i] = int(  # noqa: RUF046
                round(resolved_sizes[i] / total_resolved * cls.distributable)
            )
    actual_total = sum(resolved_sizes)
    if actual_total != cls.distributable and resolved_sizes:
        resolved_sizes[0] += cls.distributable - actual_total


def _build_resolved_nodes(
    flat_children: list[FlatNode],
    resolved_sizes: list[int],
    child_margins: list[tuple[int, int, int, int]],
    is_horizontal: bool,
    cross_content: int,
    container_name: str | None,
) -> list[ResolvedNode]:
    """Resolve cross-axis sizes, compute content areas, and recurse."""
    result: list[ResolvedNode] = []
    for idx, flat_child in enumerate(flat_children):
        child_name = flat_child.name
        comp = flat_child.component
        main_size = resolved_sizes[idx]
        margin = child_margins[idx]

        # Tableau model: children always fill the cross axis. A cross-axis size
        # (height in a horizontal container, width in a vertical one) is ignored;
        # only main-axis sizing is a per-child concept. Warn so the ignore is not
        # silent. width/height remain valid as MAIN-axis sizes (see _classify_sizes),
        # so we only inspect the cross-axis property here.
        cross_size_val = (
            getattr(comp, "height", None) if is_horizontal else getattr(comp, "width", None)
        )
        if cross_size_val is not None:
            cname = child_name or f"child[{idx}]"
            axis_prop = "height" if is_horizontal else "width"
            warnings.warn(
                f"Cross-axis size `{axis_prop}: {cross_size_val}` on `{cname}` is"
                f" ignored; container children always fill the cross axis."
                f" Use `{axis_prop}` only as a main-axis size.",
                stacklevel=2,
            )
        cross_margins = margin[0] + margin[2] if is_horizontal else margin[1] + margin[3]
        cross_size = max(cross_content - cross_margins, 0)

        if is_horizontal:
            outer_w, outer_h = main_size, cross_size
        else:
            outer_w, outer_h = cross_size, main_size

        padding = parse_spacing(getattr(comp, "padding", None))
        content_w = outer_w - padding[1] - padding[3]
        content_h = outer_h - padding[0] - padding[2]

        if content_w < 0 or content_h < 0:
            cname = child_name or f"child[{idx}]"
            pad_total = (padding[0] + padding[2], padding[1] + padding[3])
            size_val = outer_w if content_w < 0 else outer_h
            pad_val = pad_total[1] if content_w < 0 else pad_total[0]
            warnings.warn(
                f"Padding on `{cname}` ({pad_val}px) exceeds its"
                f" solved size ({size_val}px);"
                f" content area clamped to 0",
                stacklevel=2,
            )
            content_w = max(content_w, 0)
            content_h = max(content_h, 0)

        children: list[ResolvedNode] = []
        if isinstance(comp, ContainerComponent):
            child_orientation = comp.type
            child_gap = comp.gap or 0
            children = _resolve_children(
                flat_child.children,
                content_w,
                content_h,
                child_orientation,
                child_name,
                gap=child_gap,
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


def _resolve_children(
    flat_children: list[FlatNode],
    container_content_w: int,
    container_content_h: int,
    orientation: str,
    container_name: str | None,
    gap: int = 0,
) -> list[ResolvedNode]:
    """Resolve a list of FlatNode children within a container's content box."""
    if not flat_children:
        return []

    is_horizontal = orientation == "horizontal"
    main_content = container_content_w if is_horizontal else container_content_h
    cross_content = container_content_h if is_horizontal else container_content_w

    cls = _classify_sizes(flat_children, main_content, is_horizontal, gap, container_name)

    resolved_sizes: list[int] = [0] * len(flat_children)

    resolved_a = 0
    for i in cls.pct_indices:
        val = int(round(cls.buckets[i][1] * main_content))  # noqa: RUF046
        resolved_sizes[i] = val
        resolved_a += val

    resolved_b = 0
    for i in cls.px_indices:
        resolved_sizes[i] = int(cls.buckets[i][1])
        resolved_b += resolved_sizes[i]

    total_claimed = resolved_a + resolved_b

    if total_claimed <= cls.distributable:
        _resolve_underconstrained(cls, resolved_sizes, container_name, flat_children)
    elif resolved_a <= cls.distributable:
        _resolve_overconstrained_proportional(
            cls,
            resolved_sizes,
            resolved_a,
            resolved_b,
            container_name,
            flat_children,
        )
    else:
        _resolve_overconstrained_full(cls, resolved_sizes, resolved_a, resolved_b, container_name)

    return _build_resolved_nodes(
        flat_children,
        resolved_sizes,
        cls.child_margins,
        is_horizontal,
        cross_content,
        container_name,
    )


def solve_layout(flat_tree: FlatNode) -> ResolvedNode:
    """Solve the layout tree from a pre-flattened FlatNode."""
    root = flat_tree.component
    canvas = flat_tree.canvas

    if not isinstance(root, RootComponent) or canvas is None:
        raise ValueError("solve_layout requires a root FlatNode with canvas")

    # Root resolution
    root_margin = parse_spacing(root.margin)
    root_outer_w = canvas.width - root_margin[1] - root_margin[3]
    root_outer_h = canvas.height - root_margin[0] - root_margin[2]

    root_padding = parse_spacing(root.padding)
    root_content_w = max(root_outer_w - root_padding[1] - root_padding[3], 0)
    root_content_h = max(root_outer_h - root_padding[0] - root_padding[2], 0)

    root_gap = root.gap or 0

    children = _resolve_children(
        flat_tree.children,
        root_content_w,
        root_content_h,
        root.orientation,
        None,
        gap=root_gap,
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
