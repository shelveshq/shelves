"""
sidebar.js file-management UI tests — SHE-42

Runs the sidebar module in node against a mini-DOM
(tests/support/run_tree_menu.mjs) and scripts the whole flow: group-header
"+" → inline create input, 409 conflict handling, Escape cancel, the
right-click context menu (New / Rename / Duplicate / two-step Delete),
inline rename of the open file, duplicate, and click-outside dismissal.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_tree_menu.mjs"


@lru_cache(maxsize=1)
def run_session() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(RUNNER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"tree menu harness failed: {proc.stderr}"
    return proc.stdout


def facts() -> dict[str, Any]:
    return json.loads(run_session())


# ─── Create ──────────────────────────────────────────────────────


def test_group_header_has_add_button():
    assert facts()["addButtonExists"] is True


def test_add_click_shows_inline_input():
    assert facts()["createInputAppears"] is True


def test_create_posts_with_default_extension():
    # '.yaml' auto-appended, path URL-encoded, POST method
    assert facts()["createUrl"] == "/file?path=charts%2Fnewchart.yaml"
    assert facts()["createMethod"] == "POST"


def test_create_opens_the_new_file():
    assert facts()["openedAfterCreate"] == "charts/newchart.yaml"


def test_create_refetches_tree():
    assert facts()["treeRefetched"] is True


def test_create_conflict_keeps_input_with_error():
    assert facts()["dupInputStays"] is True
    assert facts()["dupInputError"] is True


def test_escape_cancels_create_input():
    assert facts()["escRemovedInput"] is True


# ─── Context menu ────────────────────────────────────────────────


def test_context_menu_items():
    assert facts()["menuItems"] == ["New file", "Rename", "Duplicate", "Delete"]


def test_context_menu_prevents_default():
    assert facts()["menuPreventedDefault"] is True


def test_menu_closes_on_outside_click():
    assert facts()["menuClosedOnOutsideClick"] is True


# ─── Delete (two-step) ───────────────────────────────────────────


def test_delete_first_click_arms_confirm():
    assert facts()["deleteFirstClickLabel"] == "Confirm delete?"
    assert facts()["noDeleteFetchYet"] is True


def test_delete_second_click_deletes_and_closes():
    assert facts()["deleteUrl"] == "/file?path=charts%2Fa.yaml"
    assert facts()["deleteMethod"] == "DELETE"
    assert facts()["menuClosedAfterDelete"] is True


# ─── Rename ──────────────────────────────────────────────────────


def test_rename_prefills_current_name():
    assert facts()["renamePrefill"] == "a.yaml"


def test_rename_calls_rename_endpoint():
    assert facts()["renameUrl"] == "/file/rename?path=charts%2Fa.yaml&to=charts%2Fb.yaml"


def test_rename_updates_open_file_path():
    assert facts()["currentFileAfterRename"] == "charts/b.yaml"


def test_rename_clears_stale_file_deleted_flag():
    assert facts()["fileDeletedCleared"] is True


# ─── Duplicate ───────────────────────────────────────────────────


def test_duplicate_reads_then_creates_copy():
    assert facts()["duplicateGet"] == "/file?path=charts%2Fa.yaml"
    assert facts()["duplicatePostUrl"] == "/file?path=charts%2Fa-copy.yaml"
    assert facts()["duplicateBody"] == "sheet: a\n"
