"""
Shelves Studio — PTY Terminal Manager

Manages pseudo-terminal subprocesses for the integrated terminal panel.
Each PtyManager instance owns one PTY and its associated shell subprocess.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import struct
import subprocess
import termios

logger = logging.getLogger("shelves.studio.terminal")

# Read chunk size from PTY master fd
_READ_CHUNK = 4096


class PtyManager:
    """
    Manages a single PTY subprocess lifecycle.

    Usage:
        mgr = PtyManager(cwd="/path/to/project")
        mgr.spawn()
        mgr.resize(24, 80)
        mgr.write(b"echo hello\r")
        data = await mgr.read()  # returns bytes
        mgr.close()
    """

    def __init__(self, cwd: str | None = None) -> None:
        """
        Args:
            cwd: Working directory for the shell subprocess.
                 Defaults to the current working directory.
        """
        self._cwd = cwd or os.getcwd()
        self._master_fd: int | None = None
        self._proc: subprocess.Popen | None = None  # type: ignore[type-arg]

    def spawn(self) -> None:
        """
        Spawn a new PTY and shell subprocess.

        Uses pty.openpty() to create master/slave fd pair.
        Launches the user's default shell ($SHELL or /bin/zsh on macOS)
        via subprocess.Popen with the slave fd as stdin/stdout/stderr.
        The shell inherits the parent process environment.

        Raises:
            OSError: If PTY creation or shell spawn fails.
        """
        master_fd, slave_fd = pty.openpty()
        shell = os.environ.get("SHELL", "/bin/zsh")
        try:
            self._proc = subprocess.Popen(
                [shell],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                env=os.environ.copy(),
                cwd=self._cwd,
            )
        finally:
            os.close(slave_fd)  # Close slave fd in parent — shell owns it now
        self._master_fd = master_fd

    def write(self, data: bytes) -> None:
        """
        Write data to the PTY master fd (i.e., send input to the shell).

        Args:
            data: Raw bytes to write (e.g., user keystrokes).
        """
        if self._master_fd is None or not data:
            return
        os.write(self._master_fd, data)

    def resize(self, rows: int, cols: int) -> None:
        """
        Resize the PTY to the given dimensions.

        Sends TIOCSWINSZ ioctl to the master fd, which delivers
        SIGWINCH to the shell subprocess.

        Args:
            rows: Number of terminal rows.
            cols: Number of terminal columns.
        """
        if self._master_fd is None:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    async def read(self) -> bytes:
        """
        Async read from the PTY master fd.

        Uses asyncio's event loop add_reader/create_future pattern
        to avoid blocking the event loop. Returns up to _READ_CHUNK bytes.

        Returns:
            bytes: Data read from the PTY. Empty bytes on EOF.

        Raises:
            OSError: If the PTY fd is invalid or closed.
        """
        fd = self._master_fd
        if fd is None:
            return b""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()

        def _on_readable() -> None:
            # Remove before reading so we don't re-fire on partial data.
            try:
                loop.remove_reader(fd)
            except (ValueError, OSError):
                pass
            try:
                data = os.read(fd, _READ_CHUNK)
            except OSError:
                data = b""
            if not future.done():
                future.set_result(data)

        loop.add_reader(fd, _on_readable)
        try:
            return await future
        except asyncio.CancelledError:
            # Cancelled while awaiting (e.g. client disconnect). Make sure
            # the future resolves so callers holding references don't leak.
            if not future.done():
                future.cancel()
            raise
        finally:
            # Always clear the reader — _on_readable may not have fired if
            # we were cancelled first, which would leave a dangling callback
            # on a soon-to-be-closed fd.
            try:
                loop.remove_reader(fd)
            except (ValueError, OSError):
                pass

    def close(self) -> None:
        """
        Close the PTY and terminate the shell subprocess.

        Closes the master fd, terminates/kills the subprocess,
        and waits for it to exit. Safe to call multiple times.
        """
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=1)
                except Exception:
                    pass
            self._proc = None

    @property
    def is_alive(self) -> bool:
        """True if the shell subprocess is still running."""
        return self._proc is not None and self._proc.poll() is None


__all__ = ["PtyManager"]
