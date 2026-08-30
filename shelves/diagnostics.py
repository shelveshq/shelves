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


class PositionedWarning(UserWarning):
    """A warning that carries the YAML loc of the field it concerns (SHE-101).

    Emission sites that know which field triggered the warning pass a `loc`
    (and a stable `code`); the studio compile route resolves the loc to a
    line/col so the marker lands inline, like an error. `str()` yields the bare
    message, so plain string consumers are unaffected.
    """

    def __init__(
        self,
        message: str,
        *,
        loc: tuple[str | int, ...] | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.loc = loc
        self.code = code


@contextmanager
def capture_structured_warnings(into: list[dict], prefix: str = "") -> Generator[None]:
    """Like `capture_warnings`, but records `{msg, loc, code}` dicts.

    `loc`/`code` come from a `PositionedWarning`; plain warnings record them as
    None. Used by the chart `/compile` route to position warning markers.
    """
    with _warnings.catch_warnings(record=True) as records:
        _warnings.simplefilter("always")
        try:
            yield
        finally:
            for record in records:
                message = record.message
                if isinstance(message, PositionedWarning):
                    loc, code = message.loc, message.code
                else:
                    loc, code = None, None
                into.append({"msg": f"{prefix}{message}", "loc": loc, "code": code})


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
