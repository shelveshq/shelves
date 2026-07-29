"""
Parameter Reference Syntax

Two forms, deliberately distinct:

  `$name`    — recognized ONLY when it is the entire scalar. Substitutes the
               raw value, preserving its Python type.
  `${name}`  — recognized inside a larger string. Always renders to text.

`$$` escapes a literal `$`, so a chart can say "Costs $$100" without the `$`
being read as a reference. Bare `$name` inside a longer string is left alone
(no substitution, no diagnostic), which keeps `$` usable in prose.
"""

from __future__ import annotations

import re
from typing import Any

WHOLE_REF_RE = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")
INTERP_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def whole_ref(scalar: Any) -> str | None:
    """Return the parameter name if `scalar` is exactly `$name`, else None.

    Only strings can be refs. `"$metric"` → `"metric"`. `"$$metric"` → None
    (escaped). `"Top $metric"` → None (bare refs are whole-scalar only).
    """
    if not isinstance(scalar, str):
        return None
    match = WHOLE_REF_RE.match(scalar)
    return match.group(1) if match else None


def interp_refs(text: str) -> list[str]:
    """Every `${name}` in `text`, in order, with repeats."""
    return INTERP_RE.findall(text)


def unescape_dollars(text: str) -> str:
    """Replace `$$` with a literal `$`.

    Applied AFTER ref detection, so `$$name` survives as the literal `$name`.
    """
    return text.replace("$$", "$")
