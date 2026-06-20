"""
label_patch.js behavior tests.

The compile-then-patch label renderer lives in the browser (label_patch.js).
Python tests can only assert the *intent* emitted into usermeta; the actual
value/placement logic is JS. These tests run the patch in node against a minimal
hand-built compiled-Vega spec and assert the inserted text mark — exercising the
JS the way the browser does, without vega/canvas.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_label_patch.mjs"


def run_patch(spec: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(spec, fh)
        spec_path = fh.name
    try:
        proc = subprocess.run(
            [node, str(RUNNER), spec_path],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(spec_path).unlink(missing_ok=True)
    assert proc.returncode == 0, f"labelPatch failed: {proc.stderr}"
    return json.loads(proc.stdout)


def text_marks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(marks: list[dict[str, Any]] | None) -> None:
        for m in marks or []:
            if m.get("type") == "text":
                found.append(m)
            walk(m.get("marks"))

    walk(spec.get("marks"))
    return found


def _bar_spec(*, intent: dict[str, Any], fill: dict[str, Any] | None = None) -> dict[str, Any]:
    """A minimal compiled-Vega vertical-bar spec (VL stack-encoded)."""
    update: dict[str, Any] = {
        "ariaRoleDescription": {"value": "bar"},
        "x": {"scale": "mark_0_x", "field": "country"},
        "y": {"scale": "mark_0_y", "field": "revenue_end"},
        "y2": {"scale": "mark_0_y", "field": "revenue_start"},
    }
    if fill is not None:
        update["fill"] = fill
    return {
        "marks": [{"type": "rect", "name": "mark_0_marks", "encode": {"update": update}}],
        "scales": [
            {
                "name": "mark_0_y",
                "type": "linear",
                "domain": {"data": "data_0", "field": "revenue_end"},
            }
        ],
        "data": [{"name": "data_0"}],
        "usermeta": {"shelves": {"labels": [intent]}},
    }


def _intent(**overrides: Any) -> dict[str, Any]:
    base = {
        "markName": "mark_0",
        "field": "revenue",
        "type": "quantitative",
        "format": None,
        "horizontal": None,
        "vertical": None,
        "size": 11,
        "color": None,
    }
    base.update(overrides)
    return base


class TestCustomFieldOnBar:
    def test_custom_label_field_drives_displayed_value(self):
        # label.field: order_count on a revenue bar → the label must show
        # order_count, not the bar's measure value.
        spec = _bar_spec(intent=_intent(field="order_count"))
        patched = run_patch(spec)
        texts = text_marks(patched)
        assert len(texts) == 1
        signal = texts[0]["encode"]["update"]["text"]["signal"]
        assert "order_count" in signal
        assert "revenue" not in signal

    def test_measure_field_still_uses_segment_value(self):
        # The default (label the measure) keeps the stacked segment value.
        spec = _bar_spec(intent=_intent(field="revenue"))
        patched = run_patch(spec)
        signal = text_marks(patched)[0]["encode"]["update"]["text"]["signal"]
        assert "revenue_end" in signal and "revenue_start" in signal


class TestMatchColorFallback:
    def test_match_without_color_encoding_falls_back_to_default(self):
        # color: match but the bar has no color scale → must fall back to the
        # default text color, never emit the literal sentinel 'match' as a color.
        spec = _bar_spec(intent=_intent(color="match"), fill=None)
        patched = run_patch(spec)
        fill = text_marks(patched)[0]["encode"]["update"]["fill"]
        assert fill == {"value": "#333333"}

    def test_match_with_color_encoding_resolves_scale(self):
        spec = _bar_spec(
            intent=_intent(color="match"),
            fill={"scale": "color", "field": "country"},
        )
        patched = run_patch(spec)
        fill = text_marks(patched)[0]["encode"]["update"]["fill"]
        assert fill == {"scale": "color", "field": "datum.country"}
