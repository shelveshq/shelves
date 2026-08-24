"""
Headless PNG rendering (SHE-56).

Converts a compiled Vega-Lite dict to PNG bytes via vl-convert (Rust wheels, no
node/browser — consistent with the no-npm rule in this package). Backs the MCP
`render_chart` tool so multimodal agents can *look* at a chart.

This path does NOT run the browser-side label patch or `compound_fit.js`, so
data labels are absent and compound specs render at natural size. See
`shelves/render/CLAUDE.md` — never use it to verify label placement or dashboard
sizing.

`vl_convert` is imported lazily so a core install can import this module; the
MCP layer turns a missing import into an install hint.
"""

from __future__ import annotations

import json
import struct

from shelves.errors import ShelvesError


class ShelvesPngError(ShelvesError):
    """vl-convert failed to render the spec to PNG."""


def render_png(vl_spec: dict, *, scale: float = 2.0) -> tuple[bytes, int, int]:
    """Render a Vega-Lite dict to ``(png_bytes, width_px, height_px)``.

    Raises ``ShelvesPngError`` on a conversion failure. A missing ``vl_convert``
    package raises ``ModuleNotFoundError`` unchanged for the caller to translate.
    """
    import vl_convert as vlc

    try:
        png = vlc.vegalite_to_png(vl_spec=json.dumps(vl_spec), scale=scale)
    except Exception as e:  # vl_convert raises its own error types
        raise ShelvesPngError(f"vl-convert could not render the spec to PNG: {e}") from e

    width, height = struct.unpack(">II", png[16:24])
    return png, width, height
