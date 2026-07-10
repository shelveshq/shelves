"""
preview.js error-overlay behavior tests (PR #59 review).

The overlay is browser DOM code; these tests run showErrorOverlay in node
against a recording document stub (tests/support/run_error_overlay.mjs) —
the same pattern as test_label_patch_js.py.

Covers two review findings:
- Empty/missing `errors` must render a fallback card, not silently no-op —
  the dashboard path hides every other pane first, so a no-op leaves a
  completely blank preview.
- The card title must be contextual: callers can pass one (dashboard compile,
  chart runtime errors) instead of always claiming "Can't compile this chart".
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_error_overlay.mjs"


def run_overlay(errors: Any, title: str | None = None) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    payload: dict[str, Any] = {"errors": errors}
    if title is not None:
        payload["title"] = title
    proc = subprocess.run(
        [node, str(RUNNER), json.dumps(payload)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"showErrorOverlay failed: {proc.stderr}"
    return json.loads(proc.stdout)


class TestEmptyErrors:
    def test_empty_array_still_shows_overlay(self):
        out = run_overlay([])
        assert out["display"] == "block"
        assert "error-card" in out["html"]

    def test_empty_array_renders_fallback_message(self):
        out = run_overlay([])
        assert "error-item" in out["html"]
        assert "without reporting" in out["html"]

    def test_null_errors_still_shows_overlay(self):
        out = run_overlay(None)
        assert out["display"] == "block"
        assert "without reporting" in out["html"]


class TestContextualTitle:
    def test_default_title_is_chart_compile(self):
        out = run_overlay(["boom"])
        assert "Can't compile this chart" in out["html"]

    def test_caller_can_override_title(self):
        out = run_overlay(["boom"], title="Can't compile this dashboard")
        assert "Can't compile this dashboard" in out["html"]
        assert "this chart" not in out["html"]

    def test_title_is_escaped(self):
        out = run_overlay(["boom"], title='<img src=x onerror="1">')
        assert "<img" not in out["html"]


class TestExistingRendering:
    """Regression guards for behavior the fix must not change."""

    def test_string_error_renders_item(self):
        out = run_overlay(["something broke"])
        assert out["display"] == "block"
        assert "something broke" in out["html"]

    def test_structured_error_renders_meta(self):
        out = run_overlay([{"msg": "bad field", "source": "yaml", "line": 3}])
        assert "YAML" in out["html"]
        assert "line 3" in out["html"]
        assert "bad field" in out["html"]

    def test_error_text_is_escaped(self):
        out = run_overlay(["<script>alert(1)</script>"])
        assert "<script>" not in out["html"]
        assert "&lt;script&gt;" in out["html"]
