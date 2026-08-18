"""Back-compat re-export.

`yaml_position` moved to the schema layer (`shelves/schema/yaml_position.py`)
when it became a shared validation concern (SHE-54): the studio compile route,
the `shelves-lint` CLI, and the MCP `validate_spec` tool all map Pydantic error
locs back to YAML line/col. This shim keeps existing `shelves.studio.yaml_position`
imports working.
"""

from __future__ import annotations

from shelves.schema.yaml_position import (
    resolve_locs,
    yaml_loc_to_position,
)

__all__ = ["resolve_locs", "yaml_loc_to_position"]
