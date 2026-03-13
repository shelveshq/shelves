"""
Data Binder

Attaches data to a compiled Vega-Lite spec.

Phase 1: Inline data only.
  bind_data(spec, rows) -> spec with data: {values: rows}

Phase 3: Will call Cube.dev REST API using the chart's data block.

For faceted specs, data goes on the TOP-LEVEL spec.
Vega-Lite propagates data from parent to faceted children.
"""

from __future__ import annotations

import copy


def bind_data(spec: dict, values: list[dict]) -> dict:
    """Attach inline data values to a Vega-Lite spec."""
    result = copy.deepcopy(spec)
    result["data"] = {"values": values}
    return result
