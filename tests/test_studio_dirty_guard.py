"""
Unsaved-changes protection (SHE-51).

Runs editor.js + state.js under node (tests/support/run_dirty_guard.mjs):
switching files over a dirty buffer must ask before discarding, re-opening
the same file stays a no-op, and a file deleted on disk under an open buffer
shows a status-bar notice + breadcrumb badge without auto-closing the buffer.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_dirty_guard.mjs"


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
    assert proc.returncode == 0, f"dirty guard harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_same_file_open_is_noop_without_prompt():
    out = run_scenarios()
    assert out["samePathPrompted"] == 0
    assert out["samePathFetches"] == 0


def test_dirty_switch_prompts_and_cancel_keeps_buffer():
    out = run_scenarios()
    assert out["cancelSettled"] is True
    assert out["cancelPrompt"] == "Discard unsaved changes to charts/a.yaml?"
    assert out["cancelPromptCount"] == 1
    assert out["cancelKeptFile"] is True
    # Exactly the side-effect-free probe GET ran before the prompt; nothing
    # downstream of the cancelled confirm may have.
    assert out["cancelFetches"] == 1
    assert out["cancelCompileStarts"] == 0


def test_clean_switch_does_not_prompt():
    assert run_scenarios()["cleanPromptCount"] == 1  # still only the cancel prompt


def test_missing_file_never_consumes_the_confirm():
    out = run_scenarios()
    assert out["notFoundStatus"] == "not-found"
    assert out["notFoundPrompts"] == 0
    assert out["notFoundKeptFile"] is True


def test_server_error_is_error_not_not_found():
    # nav.js permanently prunes history on 'not-found'; a transient 5xx must
    # report 'error' (entry kept) and must not prompt either.
    out = run_scenarios()
    assert out["serverErrorStatus"] == "error"
    assert out["serverErrorPrompts"] == 0


def test_nav_prune_walk_prompts_exactly_once():
    # SHE-40 review regression: dirty buffer + deleted entry in the back-path
    # used to prompt once per prune-loop re-entry into openFile.
    out = run_scenarios()
    assert out["navPrunePrompts"] == 1
    assert out["navPrunePromptedFor"] == "Discard unsaved changes to charts/z.yaml?"
    assert out["navPruneStack"] == ["charts/a.yaml", "charts/z.yaml"]


def test_deleted_file_shows_warn_notice_over_counts():
    out = run_scenarios()
    assert out["deletedDot"] == "sh-status-dot warn"
    assert out["deletedMsg"] == "charts/a.yaml deleted on disk — saving will recreate it"


def test_compiling_outranks_deleted_notice():
    assert run_scenarios()["compilingOverDeletedMsg"] == "Compiling…"


def test_breadcrumb_deleted_badge_tracks_flag():
    out = run_scenarios()
    assert out["deletedCrumbHasBadge"] is True
    assert out["clearedCrumbHasBadge"] is False


def test_cleared_notice_yields_to_marker_counts():
    assert run_scenarios()["clearedMsg"] == "5 errors"
