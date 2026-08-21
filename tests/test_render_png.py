"""
Unit tests for the headless PNG path (SHE-56).

`shelves.render.to_png.render_png` converts a compiled Vega-Lite dict to PNG
bytes via vl-convert (no browser). It backs the MCP `render_chart` tool, so the
agent loop can *look* at a chart. These tests exercise the pure conversion:
magic bytes, IHDR-derived dimensions, scale, and the error wrapper.
"""

from __future__ import annotations

import pytest

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

_VL = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "data": {"values": [{"a": "A", "b": 5}, {"a": "B", "b": 3}, {"a": "C", "b": 8}]},
    "mark": "bar",
    "encoding": {
        "x": {"field": "a", "type": "nominal"},
        "y": {"field": "b", "type": "quantitative"},
    },
}


def test_render_png_returns_png_bytes_and_dimensions():
    from shelves.render.to_png import render_png

    png, width, height = render_png(_VL)

    assert png[:8] == _PNG_MAGIC
    assert width > 0
    assert height > 0


def test_render_png_scale_grows_dimensions():
    from shelves.render.to_png import render_png

    _, w1, h1 = render_png(_VL, scale=1.0)
    _, w3, h3 = render_png(_VL, scale=3.0)

    assert w3 > w1
    assert h3 > h1


def test_render_png_invalid_spec_raises_shelves_error():
    from shelves.render.to_png import ShelvesPngError, render_png

    with pytest.raises(ShelvesPngError):
        render_png({"mark": "bogusmark", "encoding": {}})
