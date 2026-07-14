"""
File navigation history — back / forward (SHE-40).

Drives nav.js under node with a scripted fake openFile
(tests/support/run_nav_history.mjs) and asserts the history stack semantics:
the acceptance walk, forward-branch truncation, pruning of deleted files,
dirty-cancel abort, rename remapping, the stack cap, and the button/keyboard/
mouse bindings.
"""

from __future__ import annotations

import functools
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_nav_history.mjs"

A = "charts/a.yaml"
B = "charts/b.yaml"
C = "charts/c.yaml"
D = "charts/d.yaml"


@functools.lru_cache(maxsize=1)
def run_harness() -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(RUNNER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"nav history harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


# ── the ticket's acceptance walk ──


def test_back_back_forward_walk():
    walk = run_harness()["walk"]
    assert walk["afterOpens"] == {"stack": [A, B, C], "index": 2}
    assert walk["afterBack1"] == {"current": B, "index": 1}
    assert walk["afterBack2"] == {
        "current": A,
        "index": 0,
        "backDisabled": True,
        "fwdDisabled": False,
    }
    assert walk["afterFwd1"] == {"current": B, "index": 1}
    assert walk["afterFwd2"] == {
        "current": C,
        "index": 2,
        "backDisabled": False,
        "fwdDisabled": True,
    }


def test_back_at_start_is_noop():
    assert run_harness()["walk"]["noopCalls"] == 0


def test_navigation_never_rerecords():
    assert run_harness()["walk"]["historyCallsFromHistory"] is True


def test_new_open_truncates_forward():
    assert run_harness()["truncate"] == {"stack": [A, D], "index": 1}


# ── buttons ──


def test_button_disabled_states():
    buttons = run_harness()["buttons"]
    assert buttons["empty"] == {"back": True, "fwd": True}
    assert buttons["oneFile"] == {"back": True, "fwd": True}
    assert buttons["twoFiles"] == {"back": False, "fwd": True}


def test_button_click_navigates():
    assert run_harness()["buttons"]["clickNavigates"] is True


# ── keyboard / mouse bindings ──


def test_keyboard_shortcuts():
    kb = run_harness()["keyboard"]
    assert kb["back"] == 1 and kb["backLanded"] is True
    assert kb["fwd"] == 1 and kb["fwdLanded"] is True


def test_keyboard_skips_terminal():
    assert run_harness()["keyboard"]["terminalSkipped"] is True


def test_keyboard_skips_default_prevented():
    assert run_harness()["keyboard"]["preventedSkipped"] is True


def test_keyboard_requires_exact_chord():
    assert run_harness()["keyboard"]["shiftSkipped"] is True


def test_mouse_buttons():
    mouse = run_harness()["mouse"]
    assert mouse["back"] == 1 and mouse["backLanded"] is True
    assert mouse["fwd"] == 1 and mouse["fwdLanded"] is True


# ── edge cases ──


def test_missing_file_pruned():
    assert run_harness()["prune"] == {"current": A, "stack": [A, C], "index": 0}


def test_cancel_keeps_position():
    assert run_harness()["cancel"] == {"current": B, "stack": [A, B], "index": 1}


def test_reopen_current_no_push():
    assert run_harness()["dedupe"] == {"len": 1}


def test_rename_remaps_stack():
    rename = run_harness()["rename"]
    assert rename["stack"] == ["charts/a2.yaml", B]
    assert rename["openedWith"] == "charts/a2.yaml"
    assert rename["current"] == "charts/a2.yaml"


def test_stack_capped():
    assert run_harness()["cap"] == {"len": 100, "first": "charts/p5.yaml", "index": 99}


def test_busy_guard():
    busy = run_harness()["busy"]
    assert busy["callsDuring"] == 1
    assert busy["current"] == A


def test_error_aborts_without_prune():
    assert run_harness()["error"] == {"current": B, "stackLen": 2, "index": 1}
