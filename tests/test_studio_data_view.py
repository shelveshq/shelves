"""
Data view — resolved dataset table in the preview (SHE-43).

Runs preview.js in node against a DOM stub (tests/support/run_data_view.mjs)
and asserts the Data view's rendering: model-name header, DS table markup,
HTML escaping, numeric alignment, the 500-row cap, and the degradation
states (skipped resolution, no values, zero rows, compile errors).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_data_view.mjs"


@lru_cache(maxsize=1)
def run_scenarios() -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(RUNNER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"data view harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


# ─── Happy path ───────────────────────────────────────────────────


def test_table_renders_rows():
    out = run_scenarios()
    assert out["tableShown"] is True
    assert out["previewHidden"] is True
    assert out["overlayShownDuringTable"] is False

    html = out["tableHtml"]
    assert "orders" in html  # model name in the header
    assert "2 rows" in html
    assert "<th>country</th>" in html
    assert '<th class="is-num">revenue</th>' in html  # numeric column classed
    assert "45000" in html


def test_cells_are_escaped():
    html = run_scenarios()["tableHtml"]
    assert "a&lt;b" in html
    assert "a<b" not in html  # raw markup must never land in the DOM


def test_cell_types():
    html = run_scenarios()["tableHtml"]
    assert '<span class="sh-data-null">null</span>' in html
    assert "<td>true</td>" in html  # booleans as text, left-aligned
    assert "{&quot;x&quot;:1}" in html  # objects JSON-stringified and escaped


def test_no_footer_under_cap():
    assert "showing" not in run_scenarios()["tableHtml"]


def test_missing_model_key_renders_dash():
    assert "—" in run_scenarios()["noModelHtml"]


def test_row_cap_and_footer():
    html = run_scenarios()["capHtml"]
    assert html.count("<tr>") == 501  # 1 header row + 500 body rows
    assert "showing 500 of 1,200 rows" in html
    assert "1,200 rows" in html  # header count, locale-formatted


def test_view_change_rerenders():
    out = run_scenarios()
    assert out["rerenderShown"] is True
    assert out["rerenderOverlayHidden"] is True
    assert "<table" in out["rerenderHtml"]


# ─── Degradation states ───────────────────────────────────────────


def test_skipped_resolution_state():
    html = run_scenarios()["skippedHtml"]
    assert "Data resolution skipped: CUBE_API_URL not set" in html
    assert "sh-data-empty" in html
    assert "orders" in html  # header survives
    assert "<table" not in html


def test_no_values_no_warning_state():
    html = run_scenarios()["noValuesHtml"]
    assert "No data resolved for this chart" in html
    assert "<table" not in html


def test_zero_rows_state():
    html = run_scenarios()["zeroHtml"]
    assert "0 rows" in html
    assert "The query returned 0 rows." in html
    assert "<table" not in html


def test_ragged_rows_union_columns():
    html = run_scenarios()["raggedHtml"]
    assert '<th class="is-num">a</th>' in html
    assert "<th>b</th>" in html
    assert html.count("sh-data-null") == 1  # row 1 has no b


def test_non_array_values_shows_message():
    """A non-array top-level value in the source JSON must degrade to a
    message — not a TypeError leaving the previous table visible (PR #67)."""
    html = run_scenarios()["nonArrayHtml"]
    assert "not a list of rows" in html
    assert "sh-data-empty" in html
    assert "<table" not in html


def test_null_values_shows_message():
    html = run_scenarios()["nullValuesHtml"]
    assert "not a list of rows" in html
    assert "<table" not in html


def test_null_row_renders_null_cells():
    """A null row inside the array renders as a row of null cells."""
    html = run_scenarios()["nullRowHtml"]
    assert "<table" in html
    assert html.count("<tr>") == 3  # header + 2 body rows
    assert '<th class="is-num">a</th>' in html
    assert html.count("sh-data-null") == 1  # the null row's single cell


def test_error_result_shows_overlay():
    out = run_scenarios()
    assert out["errorOverlayShown"] is True
    assert out["dataViewHiddenOnError"] is True


def test_null_spec_no_errors_hides_data_view():
    assert run_scenarios()["dataViewHiddenOnEmpty"] is True
