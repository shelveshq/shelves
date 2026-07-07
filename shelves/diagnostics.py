"""
Structured Diagnostics Helpers

Python's `warnings.warn` only reaches CLI users (stderr). Studio users see a
structured `warnings: [...]` list in each compile response — anything emitted
via the warnings machinery (KPI shelf conflicts, tooltip disaggregation,
legend link notices) is invisible to them unless captured.

`capture_warnings` bridges the two: it records every warning emitted inside
the block into a plain list of strings, which route handlers and the dashboard
pipeline return in their structured payload. Emission sites keep using
`warnings.warn` (the right idiom for library code); capture happens once at
the surface boundary.

Caveats: the warnings filter state is process-global, so the context is not
thread-safe, and the block must not contain an `await` (another coroutine's
warnings would be captured into the wrong list).
"""

from __future__ import annotations

import warnings as _warnings
from collections.abc import Generator
from contextlib import contextmanager


@contextmanager
def capture_warnings(into: list[str], prefix: str = "") -> Generator[None]:
    """Record warnings emitted inside the block into `into` as strings.

    Each warning message is appended as `f"{prefix}{message}"`. Warnings are
    captured (not re-emitted); recording survives an exception raised inside
    the block so partial work still surfaces its warnings.
    """
    with _warnings.catch_warnings(record=True) as records:
        _warnings.simplefilter("always")
        try:
            yield
        finally:
            for record in records:
                into.append(f"{prefix}{record.message}")
