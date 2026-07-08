"""
Shared Exception Hierarchy

Every error Shelves raises on purpose derives from ShelvesError, so surfaces
(CLIs, Studio routes, compose) can catch Shelves failures precisely instead of
blanket `except Exception`, and let genuinely unexpected bugs propagate loudly.

Concrete error types stay in the module that raises them (e.g. CubeError in
shelves/data/cube_client.py) — this module only owns the base class so it
never grows import-order problems.
"""

from __future__ import annotations


class ShelvesError(Exception):
    """Base class for all errors deliberately raised by Shelves."""
