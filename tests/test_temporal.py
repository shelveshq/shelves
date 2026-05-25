"""
Tests for shelves/schema/temporal.py — shared temporal constants.
"""

from __future__ import annotations


def test_grain_to_time_unit_contents():
    from shelves.schema.temporal import GRAIN_TO_TIME_UNIT

    assert GRAIN_TO_TIME_UNIT == {
        "day": "yearmonthdate",
        "week": "yearweek",
        "month": "yearmonth",
        "quarter": "yearquarter",
        "year": "year",
    }
