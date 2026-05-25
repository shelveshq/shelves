"""
Temporal Constants

Shared grain-to-Vega-Lite timeUnit mapping used by both the model resolver
and Cube query builder.
"""

from __future__ import annotations

GRAIN_TO_TIME_UNIT: dict[str, str] = {
    "day": "yearmonthdate",
    "week": "yearweek",
    "month": "yearmonth",
    "quarter": "yearquarter",
    "year": "year",
}
