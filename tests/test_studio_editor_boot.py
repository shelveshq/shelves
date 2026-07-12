"""
Studio boot resilience (SHE-64).

Boot used to serialize the whole UI behind Monaco's CDN load (`await
initEditor()` at main.js top level): slow CDN = seconds of blank UI, failed
CDN = blank forever with no in-page error. Now boot is parallel and the
editor guards its own failure.

The failure path runs for real in node (tests/support/run_editor_boot.mjs):
node cannot import https URLs, which is the same shape as the browser's
"Monaco import rejected" mode. The parallel-boot ordering and the first-paint
placeholders are asserted on the sources — they are static properties of
main.js / index.html.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_editor_boot.mjs"
STATIC = Path(__file__).parent.parent / "shelves" / "studio" / "static"


@lru_cache(maxsize=1)
def run_boot_failure() -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(RUNNER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"editor boot harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


class TestEditorLoadFailure:
    def test_init_editor_never_propagates(self):
        """A rejected Monaco load must not escape initEditor — that rejection
        is what used to abort main.js and blank every pane."""
        assert run_boot_failure()["initEditorPropagatedError"] is False

    def test_error_card_painted(self):
        out = run_boot_failure()
        assert out["bootIsError"] is True
        assert "Editor failed to load" in out["bootHtml"]
        assert "ad-blocker" in out["bootHtml"]

    def test_open_file_bails_out_cleanly(self):
        """Clicking a file with a dead editor: no throw, no fetch, and no
        compile-start veil that nothing would ever terminate."""
        out = run_boot_failure()
        assert out["openFilePropagatedError"] is False
        assert out["openFileFetchCount"] == 0
        assert "shelves:compile-start" not in out["openFileDispatched"]

    def test_load_timeout_timer_cleared_after_settle(self):
        """PR#60 review (r3565908567): the 20s timeout timer must not stay
        pending after the boot race settles."""
        out = run_boot_failure()
        assert out["bootTimeoutTimerCount"] == 1
        assert out["bootTimeoutTimerCleared"] is True


class TestParallelBoot:
    def test_main_no_longer_awaits_editor_or_terminal(self):
        main = (STATIC / "js" / "main.js").read_text()
        assert "await initEditor" not in main
        assert "await initTerminal" not in main

    def test_tree_and_ws_boot_before_monaco(self):
        main = (STATIC / "js" / "main.js").read_text()
        assert main.index("initSidebar()") < main.index("initEditor()")
        assert main.index("connectWebSocket()") < main.index("initEditor()")


class TestFirstPaintPlaceholders:
    def test_file_tree_has_pending_state(self):
        index = (STATIC / "index.html").read_text()
        assert '<div id="file-tree"><div class="tree-placeholder">' in index

    def test_editor_pane_has_boot_veil(self):
        index = (STATIC / "index.html").read_text()
        assert 'id="editor-boot"' in index
        assert "sh-boot-pill" in index
