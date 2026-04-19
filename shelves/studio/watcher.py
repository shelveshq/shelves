"""
Shelves Studio — File Watcher

watchfiles-based async file watcher that detects changes in the project
directory and invokes a callback for broadcast over WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine

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
    project_dir: Path,
    on_change: Callable[[str, Path], Coroutine[Any, Any, None]],
    stop_event: asyncio.Event | None = None,
) -> None:
    """
    Watch a project directory for file changes and invoke a callback.

    Args:
        project_dir: Absolute path to the project directory to watch.
        on_change: Async callback invoked for each relevant file change.
                   Signature: on_change(event: str, path: Path)
                   where event is "created", "modified", or "deleted".
        stop_event: Optional asyncio.Event. When set, the watcher stops.
    """
    try:
        async for changes in awatch(project_dir, stop_event=stop_event):
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
