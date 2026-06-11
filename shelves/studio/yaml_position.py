from __future__ import annotations

import re

_TYPED_COLLECTION_RE = re.compile(r"^(list|dict|set)\[")


def _is_synthetic_segment(segment: object) -> bool:
    """True if a loc segment is a Pydantic-synthesized label, not a user key.

    These appear in ``ValidationError.errors()[*]["loc"]`` for tagged/typed
    unions: literal tags like ``literal['bar',...]``, model-class names like
    ``MarkObject``, and typed-collection labels like ``list[str]``. None of
    them correspond to a key the user actually typed.
    """
    if not isinstance(segment, str):
        return False
    if segment.startswith("literal["):
        return True
    if _TYPED_COLLECTION_RE.match(segment):
        return True
    return bool(segment[0:1].isupper() and segment.isidentifier())


def _load_root(yaml_text: str):
    """Round-trip parse ``yaml_text`` into a CommentedMap, or None on failure."""
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap

    ry = YAML()
    try:
        root = ry.load(yaml_text)
    except Exception:
        return None
    if not isinstance(root, CommentedMap):
        return None
    return root


def _resolve_position(
    root,
    loc: tuple[str | int, ...],
    *,
    position: str = "key",
) -> tuple[int, int] | None:
    """Walk ``loc`` over a parsed ``root`` and return its (line, col)."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if not loc:
        return _to_1based((root.lc.line, root.lc.col))

    current: object = root
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
                if _is_synthetic_segment(segment):
                    continue
                return None
            if is_last:
                if position == "value":
                    return _to_1based(current.lc.value(segment))
                return _to_1based(current.lc.key(segment))
            last_position = current.lc.key(segment)
            current = current[segment]

    return _to_1based(last_position)


def _clean_display_loc(root, loc: tuple[str | int, ...]) -> list:
    """Strip synthetic labels from ``loc`` while keeping real (present) keys.

    Walks the document alongside ``loc`` so a segment is only treated as
    synthetic when it is *absent* from the current node — a present key that
    happens to be capitalized (e.g. a user field ``Region``) is preserved.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    cleaned: list = []
    current: object = root
    for segment in loc:
        if isinstance(segment, int):
            cleaned.append(segment)
            if isinstance(current, CommentedSeq) and 0 <= segment < len(current):
                current = current[segment]
            else:
                current = None
            continue

        if isinstance(current, CommentedMap) and segment in current:
            cleaned.append(segment)
            current = current[segment]
        elif _is_synthetic_segment(segment):
            continue
        else:
            cleaned.append(segment)
            current = None
    return cleaned


def _pattern_clean(loc: tuple[str | int, ...]) -> list:
    """Best-effort display cleaning when the document could not be parsed."""
    return [seg for seg in loc if not _is_synthetic_segment(seg)]


def yaml_loc_to_position(
    yaml_text: str,
    loc: tuple[str | int, ...],
    *,
    position: str = "key",
) -> tuple[int, int] | None:
    """Map a Pydantic ValidationError loc tuple to a (line, col) in the YAML source."""
    root = _load_root(yaml_text)
    if root is None:
        return None
    return _resolve_position(root, loc, position=position)


def resolve_locs(
    yaml_text: str,
    locs: list[tuple[str | int, ...]],
) -> list[dict]:
    """Resolve many loc tuples against a single parse of ``yaml_text``.

    Returns one dict per loc with ``position`` ((line, col) or None) and a
    cleaned ``display_loc``. Parsing once avoids re-parsing the document for
    every validation error.
    """
    root = _load_root(yaml_text)
    out: list[dict] = []
    for loc in locs:
        if root is None:
            out.append({"position": None, "display_loc": _pattern_clean(loc)})
        else:
            out.append(
                {
                    "position": _resolve_position(root, loc),
                    "display_loc": _clean_display_loc(root, loc),
                }
            )
    return out


def _to_1based(pos: tuple[int, int]) -> tuple[int, int]:
    return (pos[0] + 1, pos[1] + 1)
