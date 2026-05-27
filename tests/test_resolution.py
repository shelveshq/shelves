"""
Resolution Cascade Tests

Unit tests for translator/resolution.py — mark and property cascade helpers.
"""

import pytest

from shelves.translator.resolution import resolve_mark, resolve_property


class TestResolveMark:
    def test_layer_wins(self):
        assert resolve_mark("bar", "line", "area", "revenue") == "bar"

    def test_entry_wins_when_no_layer(self):
        assert resolve_mark(None, "bar", "line", "revenue") == "bar"

    def test_top_level_fallback(self):
        assert resolve_mark(None, None, "line", "revenue") == "line"

    def test_raises_when_all_none(self):
        with pytest.raises(ValueError, match="No mark defined for measure 'revenue'"):
            resolve_mark(None, None, None, "revenue")

    def test_two_level_shorthand(self):
        """stacked.py's old 2-level call uses resolve_mark(None, entry_mark, top_mark, name)."""
        assert resolve_mark(None, "bar", "line", "revenue") == "bar"
        assert resolve_mark(None, None, "line", "revenue") == "line"


class TestResolveProperty:
    def test_layer_wins(self):
        assert resolve_property("#red", "country", "region") == "#red"

    def test_entry_wins_when_no_layer(self):
        assert resolve_property(None, "country", "region") == "country"

    def test_top_level_fallback(self):
        assert resolve_property(None, None, "region") == "region"

    def test_all_none_returns_none(self):
        assert resolve_property(None, None, None) is None
