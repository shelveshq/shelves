"""
Shelves Studio — File Watcher

watchfiles-based async file watcher that detects changes in the project
directory and invokes a callback for broadcast over WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
import os
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
    project_dir: Path,
    scope_dirs: list[Path],
    on_change: Callable[[str, Path], Coroutine[Any, Any, None]],
    stop_event: asyncio.Event | None = None,
) -> None:
    """
    Watch project_dir, invoking on_change only for files inside scope_dirs.

    The watch is rooted at project_dir — which always exists — and the
    SHE-39 scoping is an event filter, not a watch-root restriction. awatch
    raises on nonexistent paths and never adds new roots, so rooting the
    watch at the scope dirs themselves would silently lose live reload for
    any dir created after startup (PR #62 review finding).

    Args:
        project_dir: Absolute path of the project directory to watch.
        scope_dirs: The configured charts/dashboards/models/assets dirs (or
                    files); events outside all of them are dropped. Entries
                    outside project_dir simply never match.
        on_change: Async callback invoked for each relevant file change.
                   Signature: on_change(event: str, path: Path)
                   where event is "created", "modified", or "deleted".
        stop_event: Optional asyncio.Event. When set, the watcher stops.
    """
    scope = [d.resolve() for d in scope_dirs]

    def in_scope(real: Path) -> bool:
        return any(real.is_relative_to(d) for d in scope)

    def scan_new_dir(root: Path) -> list[Path]:
        """Watchable files inside a just-created dir, filtered like live events."""
        if not (in_scope(root) or any(d.is_relative_to(root) for d in scope)):
            return []
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.startswith(".") or Path(name).suffix not in WATCH_EXTENSIONS:
                    continue
                f = (Path(dirpath) / name).resolve()
                if in_scope(f):
                    found.append(f)
        return sorted(found)

    try:
        async for changes in awatch(project_dir, stop_event=stop_event):
            batch: list[tuple[str, Path]] = []
            seen: set[Path] = set()
            new_dirs: list[Path] = []
            for change_type, path_str in changes:
                path = Path(path_str)
                if path.name.startswith("."):
                    continue
                # Compare resolved-to-resolved: watchfiles reports real paths,
                # which won't prefix-match a symlinked configured dir raw.
                real = path.resolve()
                if change_type == Change.added and real.is_dir():
                    new_dirs.append(real)
                    continue
                if path.suffix not in WATCH_EXTENSIONS:
                    continue
                if not in_scope(real):
                    continue
                batch.append((_CHANGE_NAMES.get(change_type, "modified"), path))
                seen.add(real)
            # Linux inotify only registers a watch on a new directory after
            # its creation event reaches us — files written into it in that
            # window emit no events of their own. Rescan each new dir and
            # synthesize "created" for anything the live stream missed.
            for d in new_dirs:
                for f in scan_new_dir(d):
                    if f not in seen:
                        seen.add(f)
                        batch.append(("created", f))
            for event, path in batch:
                try:
                    await on_change(event, path)
                except Exception:
                    logger.exception("Error in on_change callback for %s", path)
    except asyncio.CancelledError:
        logger.debug("File watcher cancelled, stopping.")
    except Exception:
        logger.exception("File watcher encountered an unexpected error.")
        raise
