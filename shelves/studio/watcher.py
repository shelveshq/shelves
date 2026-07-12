"""
Shelves Studio — File Watcher

watchfiles-based async file watcher that detects changes in the project
directory and invokes a callback for broadcast over WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from watchfiles import Change, awatch

logger = logging.getLogger("shelves.studio.watcher")

# File extensions that trigger compilation (parse_chart → translate_chart)
COMPILE_EXTENSIONS = {".yaml", ".yml"}

# File extensions that produce file_change events (for the file explorer)
WATCH_EXTENSIONS = {".yaml", ".yml", ".json"}

_CHANGE_NAMES = {
    Change.added: "created",
    Change.modified: "modified",
    Change.deleted: "deleted",
}


def should_compile(path: Path) -> bool:
    """
    Return True if this file should trigger recompilation.

    Only YAML files (.yaml, .yml) are compiled. JSON and other extensions
    produce file_change events but no compile_result.
    """
    return path.suffix in COMPILE_EXTENSIONS


async def watch_project(
    watch_dirs: list[Path],
    on_change: Callable[[str, Path], Coroutine[Any, Any, None]],
    stop_event: asyncio.Event | None = None,
) -> None:
    """
    Watch the configured project dirs for file changes and invoke a callback.

    Args:
        watch_dirs: Absolute paths of the directories to watch (SHE-39: the
                    configured charts/dashboards/models dirs, not the whole
                    project). Missing dirs are filtered out — awatch raises
                    on nonexistent paths — so dirs created after startup are
                    not picked up until a restart.
        on_change: Async callback invoked for each relevant file change.
                   Signature: on_change(event: str, path: Path)
                   where event is "created", "modified", or "deleted".
        stop_event: Optional asyncio.Event. When set, the watcher stops.
    """
    dirs = [d for d in watch_dirs if d.is_dir()]
    if not dirs:
        logger.info("No watch dirs exist; file watcher idle.")
        return
    try:
        async for changes in awatch(*dirs, stop_event=stop_event):
            for change_type, path_str in changes:
                path = Path(path_str)
                if path.name.startswith("."):
                    continue
                if path.suffix not in WATCH_EXTENSIONS:
                    continue
                event = _CHANGE_NAMES.get(change_type, "modified")
                try:
                    await on_change(event, path)
                except Exception:
                    logger.exception("Error in on_change callback for %s", path)
    except asyncio.CancelledError:
        logger.debug("File watcher cancelled, stopping.")
    except Exception:
        logger.exception("File watcher encountered an unexpected error.")
        raise
