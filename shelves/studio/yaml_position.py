from __future__ import annotations


def yaml_loc_to_position(
    yaml_text: str,
    loc: tuple[str | int, ...],
    *,
    position: str = "key",
) -> tuple[int, int] | None:
    """Map a Pydantic ValidationError loc tuple to a (line, col) in the YAML source."""
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    ry = YAML()
    try:
        root = ry.load(yaml_text)
    except Exception:
        return None

    if not isinstance(root, CommentedMap):
        return None

    if not loc:
        return _to_1based((root.lc.line, root.lc.col))

    current: CommentedMap | CommentedSeq | object = root
    last_position: tuple[int, int] = (root.lc.line, root.lc.col)

    for i, segment in enumerate(loc):
        is_last = i == len(loc) - 1

        if isinstance(segment, int):
            if not isinstance(current, CommentedSeq):
                return _to_1based(last_position)
            if segment >= len(current):
                return None
            if is_last:
                return _to_1based(current.lc.item(segment))
            last_position = current.lc.item(segment)
            current = current[segment]

        elif isinstance(segment, str):
            if not isinstance(current, CommentedMap):
                return _to_1based(last_position)
            if segment not in current:
                if _is_discriminator_label(segment):
                    continue
                return None
            if is_last:
                if position == "value":
                    return _to_1based(current.lc.value(segment))
                return _to_1based(current.lc.key(segment))
            last_position = current.lc.key(segment)
            current = current[segment]

    return _to_1based(last_position)


def _to_1based(pos: tuple[int, int]) -> tuple[int, int]:
    return (pos[0] + 1, pos[1] + 1)


def _is_discriminator_label(segment: str) -> bool:
    """Detect Pydantic union discriminator labels like "literal['bar',...]" or "MarkObject"."""
    if segment.startswith("literal["):
        return True
    return segment[0:1].isupper() and segment.isidentifier()
