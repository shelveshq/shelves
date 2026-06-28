"""
Legend → scale linking + in-sheet legend suppression tests (SHE-10).

Two layers:
  - TestLegendLinkHelpers: unit tests of the pure helpers in
    shelves.compose.legend_link, using hand-built encodings + a fake resolver.
  - TestLegendCompose: integration tests through compose_dashboard, asserting the
    emitted data attributes and the suppressed `legend: null` in the embedded
    specs JSON.
"""

import json
import re

import pytest

from shelves.compose.dashboard import compose_dashboard
from shelves.compose.legend_link import (
    find_legend_scale,
    legend_producing_channels,
    resolve_legend_links,
    suppress_in_sheet_legend,
)
from shelves.schema.field_types import VegaLiteType
from shelves.schema.layout_schema import LegendComponent
from shelves.translator.layout_styles import LegendLink
from tests.conftest import DATA_DIR, LAYOUT_DIR, MODELS_DIR, YAML_DIR

# ─── Helpers ──────────────────────────────────────────────────────


class FakeResolver:
    """Minimal FieldTypeResolver. Only resolve_base_field is exercised by the
    legend helpers; the rest are protocol-satisfying stubs."""

    def resolve(self, field_name: str) -> VegaLiteType:
        return "nominal"

    def resolve_base_field(self, field_ref: str) -> str:
        return field_ref.split(".", 1)[0]

    def resolve_time_unit(self, field_ref: str) -> str | None:
        return None

    def resolve_label(self, field_ref: str) -> str:
        return field_ref

    def resolve_format(self, field_ref: str) -> str | None:
        return None

    def resolve_default_sort(self, field_ref: str) -> str | None:
        return None

    def resolve_sort_order(self, field_ref: str) -> list[str] | None:
        return None

    def resolve_grain(self, field_ref: str) -> str | None:
        return None

    def is_measure(self, field_ref: str) -> bool:
        return False


def _compose(fixture_name: str, **kwargs) -> str:
    """Compose a dashboard from a layout fixture (mirrors test_dashboard_compose)."""
    return compose_dashboard(
        dashboard_path=LAYOUT_DIR / fixture_name,
        chart_base_dir=YAML_DIR,
        data_dir=DATA_DIR,
        models_dir=MODELS_DIR,
        **kwargs,
    )


def _legend_attrs(html: str) -> str:
    """Return the attribute string between the legend div's id and style."""
    m = re.search(r'<div id="legend-[^"]+"([^>]*) style=', html)
    assert m is not None, "legend div not found"
    return m.group(1)


def _embedded_specs(html: str) -> dict:
    """Parse the `const specs = {...};` block from the dashboard HTML."""
    m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
    assert m is not None, "embedded specs block not found"
    return json.loads(m.group(1))


# ─── Unit: pure helpers ───────────────────────────────────────────


class TestLegendLinkHelpers:
    def test_find_scale_color(self):
        enc = {
            "x": {"field": "country"},
            "color": {"field": "country", "type": "nominal", "legend": {"title": "Country"}},
        }
        assert find_legend_scale("country", enc, FakeResolver()) == "color"

    def test_find_scale_size(self):
        enc = {
            "color": {"field": "country"},
            "size": {"field": "revenue", "type": "quantitative"},
        }
        assert find_legend_scale("revenue", enc, FakeResolver()) == "size"

    def test_find_scale_none(self):
        enc = {
            "x": {"field": "country"},
            "y": {"field": "revenue"},
            "color": {"field": "country"},
        }
        assert find_legend_scale("region", enc, FakeResolver()) is None

    def test_producing_channels(self):
        enc = {
            "color": {"value": "#4A90D9"},
            "size": {"field": "revenue"},
            "x": {"field": "country"},
        }
        assert legend_producing_channels(enc) == ["size"]

    def test_suppress(self):
        enc = {"color": {"field": "country", "legend": {"title": "Country"}}}
        suppress_in_sheet_legend(enc, "color")
        assert enc["color"]["legend"] is None
        # Channel with no prior legend key still gets legend=None:
        enc2 = {"size": {"field": "revenue"}}
        suppress_in_sheet_legend(enc2, "size")
        assert enc2["size"]["legend"] is None

    def test_resolve_links_happy(self):
        color_enc = {"field": "country", "type": "nominal", "legend": {"title": "Country"}}
        vls = {
            "sales_chart": {
                "mark": "bar",
                "encoding": {"x": {"field": "country"}, "color": color_enc},
            }
        }
        sheets = {"sales_chart": "simple_bar.yaml"}
        resolvers = {"sales_chart": FakeResolver()}
        legends = [LegendComponent(source="simple_bar.yaml", field="country")]

        links, warns = resolve_legend_links(legends, sheets, vls, resolvers)

        assert links == {
            ("simple_bar.yaml", "country"): LegendLink(
                sheet_id="sheet-sales_chart", title="country", channel="color"
            )
        }
        # In-sheet legend suppressed on the linked channel:
        assert vls["sales_chart"]["encoding"]["color"]["legend"] is None
        # Linked channel does NOT warn:
        assert warns == []

    def test_resolve_links_does_not_prefix_named_spec(self):
        # When the compiled VL unit spec carries a top-level `name` (set by the
        # labels machinery, e.g. "mark_0"), Vega-Lite namespaces every scale as
        # `{name}_{channel}` at runtime. SHE-28: Python no longer reconstructs
        # that compiled name — the LegendLink carries only the bare channel, and
        # the browser resolves the live scale from it against the live view.
        color_enc = {"field": "country", "type": "nominal", "legend": {"title": "Country"}}
        vls = {
            "sales_chart": {
                "name": "mark_0",
                "mark": "circle",
                "encoding": {"x": {"field": "country"}, "color": color_enc},
            }
        }
        sheets = {"sales_chart": "labeled.yaml"}
        resolvers = {"sales_chart": FakeResolver()}
        legends = [LegendComponent(source="labeled.yaml", field="country")]

        links, _ = resolve_legend_links(legends, sheets, vls, resolvers)

        link = links[("labeled.yaml", "country")]
        # Python emits intent only — the bare channel. No reconstructed scale name.
        assert link.channel == "color"
        assert not hasattr(link, "scale")

    def test_resolve_links_explicit_empty_title_preserved(self):
        # An explicit `title: ""` suppresses the heading and must NOT fall back
        # to the model label (empty string is meaningful, not "unset").
        color_enc = {"field": "country", "type": "nominal"}
        vls = {"s": {"mark": "bar", "encoding": {"color": color_enc}}}
        sheets = {"s": "chart.yaml"}
        resolvers = {"s": FakeResolver()}
        legends = [LegendComponent(source="chart.yaml", field="country", title="")]

        links, _ = resolve_legend_links(legends, sheets, vls, resolvers)

        assert links[("chart.yaml", "country")].title == ""

    def test_resolve_links_warns_unlinked(self):
        vls = {"s": {"mark": "bar", "encoding": {"color": {"field": "country"}}}}
        sheets = {"s": "chart.yaml"}
        resolvers = {"s": FakeResolver()}

        links, warns = resolve_legend_links([], sheets, vls, resolvers)

        assert links == {}
        # Always-suppress even with no legend element:
        assert vls["s"]["encoding"]["color"]["legend"] is None
        assert len(warns) == 1
        assert "color" in warns[0]
        assert "no dashboard legend" in warns[0]

    def test_resolve_links_errors(self):
        color_enc = {"field": "country", "type": "nominal"}
        vls = {"s": {"mark": "bar", "encoding": {"color": color_enc}}}
        sheets = {"s": "chart.yaml"}
        resolvers = {"s": FakeResolver()}

        # Source matches no sheet:
        with pytest.raises(ValueError, match="no sheet"):
            resolve_legend_links(
                [LegendComponent(source="other.yaml", field="country")], sheets, vls, resolvers
            )

        # Field not encoded on a legend channel:
        with pytest.raises(ValueError, match="not encoded"):
            resolve_legend_links(
                [LegendComponent(source="chart.yaml", field="region")], sheets, vls, resolvers
            )

        # Compound spec (no top-level encoding) → not supported yet:
        vls_compound = {"s": {"layer": [], "resolve": {}}}
        with pytest.raises(ValueError, match="not supported yet"):
            resolve_legend_links(
                [LegendComponent(source="chart.yaml", field="country")],
                sheets,
                vls_compound,
                resolvers,
            )


# ─── Integration: compose_dashboard ───────────────────────────────


class TestLegendCompose:
    def test_compose_color_legend_links_and_suppresses(self):
        html = _compose("legend_link_color.yaml")

        attrs = _legend_attrs(html)
        assert 'data-source="sheet-sales_chart"' in attrs
        assert 'data-channel="color"' in attrs
        # SHE-28: Python emits only the channel intent — no compile-time scale name.
        assert "data-scale" not in attrs

        specs = _embedded_specs(html)
        assert specs["sheet-sales_chart"]["encoding"]["color"]["legend"] is None

    def test_compose_size_legend(self):
        # scatter.yaml also has color:country with no legend element → one warning.
        with pytest.warns(UserWarning, match="color"):
            html = _compose("legend_link_size.yaml")

        attrs = _legend_attrs(html)
        assert 'data-channel="size"' in attrs
        assert "data-scale" not in attrs
        assert 'data-source="sheet-scatter_chart"' in attrs

        specs = _embedded_specs(html)
        enc = specs["sheet-scatter_chart"]["encoding"]
        assert enc["size"]["legend"] is None
        assert enc["color"]["legend"] is None

    def test_compose_labeled_chart_emits_channel_not_scale(self):
        """A chart with labels carries name: mark_0, so VL namespaces its color
        scale as mark_0_color at runtime. SHE-28: Python emits only the bare
        channel — it no longer reconstructs the namespaced scale name. The
        browser resolves mark_0_color from the channel against the live view."""
        html = _compose("legend_link_labeled.yaml")

        attrs = _legend_attrs(html)
        assert 'data-channel="color"' in attrs
        assert "data-scale" not in attrs

        specs = _embedded_specs(html)
        assert specs["sheet-labeled_chart"]["encoding"]["color"]["legend"] is None

    def test_compose_legend_before_sheet_keeps_sheet_ids_aligned(self):
        """A legend preceding an anonymous sheet must not offset later sheets'
        DOM ids from their embedded-spec keys. Regression: sheets and legends
        shared one auto-id counter in the renderer, but sheet discovery counted
        only sheets — so a sheet after a legend rendered as sheet-auto-(N+1)
        while its spec was keyed sheet-auto-N, and never mounted (disappeared)."""
        with pytest.warns(UserWarning):
            html = _compose("legend_before_sheet.yaml")

        dom_sheet_ids = set(re.findall(r'id="(sheet-auto-\d+)"', html))
        spec_keys = set(_embedded_specs(html).keys())
        assert dom_sheet_ids == spec_keys

    def test_compose_unlinked_channel_warns(self):
        with pytest.warns(UserWarning, match=r"sales_chart.*color.*no dashboard legend"):
            html = _compose("legend_unlinked.yaml")

        specs = _embedded_specs(html)
        assert specs["sheet-sales_chart"]["encoding"]["color"]["legend"] is None

    def test_compose_bad_source_raises(self):
        with pytest.raises(ValueError, match=r"heatmap\.yaml.*no sheet"):
            _compose("legend_bad_source.yaml")

    def test_compose_field_not_encoded_raises(self):
        with pytest.raises(ValueError, match=r"revenue.*not encoded"):
            _compose("legend_field_not_encoded.yaml")

    def test_compose_layered_not_supported_raises(self):
        with pytest.raises(ValueError, match=r"not supported yet"):
            _compose("legend_layered.yaml")
