"""
Parameter CLI Tests (SHE-91)

`--param key=value` and `--parameters-file` are the last mile of the parameter
model: the first surface input that can supply a value. Two layers are covered
here —

  * `shelves/params/coerce.py`  — flag parsing and raw string → declared type
  * `shelves/params/resolve.py` — `load_parameter_set`, the single builder every
    surface calls (load declarations, resolve SHE-90 domains, coerce, construct)

plus the render CLI's flag wiring and its exit-2 contract for a correctable
error.

Coercion is driven by the DECLARED type, never inferred from the string: a
`--param status=10` stays the string "10" because `status` is `type: string`.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from pathlib import Path

import pytest

from shelves.data.domains import clear_domain_cache
from shelves.data.errors import ParameterDomainError
from shelves.models.loader import clear_model_cache
from shelves.params.coerce import coerce_override, parse_param_flags
from shelves.params.resolve import load_parameter_set
from tests.conftest import DATA_DIR, FIXTURES_DIR, MODELS_DIR, YAML_DIR, params_fixture

_ONE_PARAM_FILE = """
parameters:
  metric:
    type: field
    values:
      - model: orders
        field: revenue
      - model: orders
        field: cost
    default: cost
"""


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_model_cache()
    clear_domain_cache()
    yield
    clear_model_cache()
    clear_domain_cache()


@pytest.fixture
def load():
    """Load the shared parameters fixture with string overrides.

    The fixture declares three field-reference domains against `orders`, whose
    inline source path is relative — so `data_base_dir` is mandatory, not
    decoration. Every caller here gets the same pairing.
    """

    def _load(**overrides: str):
        return load_parameter_set(
            params_fixture(),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
            overrides=overrides,
        )

    return _load


# ─── Flag parsing ─────────────────────────────────────────────────


class TestFlagParsing:
    def test_repeated_param_flags(self):
        assert parse_param_flags(["metric=cost", "region=APAC", "top_n=25"]) == {
            "metric": "cost",
            "region": "APAC",
            "top_n": "25",
        }

    def test_render_parser_appends_param_flags(self):
        import shelves.cli.render as render

        parser = render.build_parser()
        args = parser.parse_args(["c.yaml", "--param", "metric=cost", "--param", "top_n=25"])
        assert args.param == ["metric=cost", "top_n=25"]

    def test_render_parser_param_defaults_to_empty_list(self):
        """argparse action="append" defaults to None unless told otherwise."""
        import shelves.cli.render as render

        args = render.build_parser().parse_args(["c.yaml"])
        assert args.param == []
        assert args.parameters_file is None

    def test_dev_parser_appends_param_flags(self):
        import shelves.cli.dev as dev

        parser = dev.build_parser()
        args = parser.parse_args(
            ["c.yaml", "--param", "metric=cost", "--parameters-file", "p.yaml"]
        )
        assert args.param == ["metric=cost"]
        assert args.parameters_file == "p.yaml"

    def test_value_may_contain_equals(self):
        """Split on the FIRST `=` only."""
        assert parse_param_flags(["region=A=B"]) == {"region": "A=B"}

    def test_empty_value_is_kept(self):
        assert parse_param_flags(["status="]) == {"status": ""}

    def test_repeated_key_last_wins(self):
        assert parse_param_flags(["metric=cost", "metric=arpu"]) == {"metric": "arpu"}

    def test_no_flags_is_empty_mapping(self):
        assert parse_param_flags([]) == {}


class TestFlagParsingErrors:
    # C9
    def test_missing_equals_raises(self):
        with pytest.raises(ValueError) as exc:
            parse_param_flags(["metric"])
        assert str(exc.value) == (
            "--param metric: expected key=value, e.g. --param metric=revenue."
        )

    def test_empty_key_raises(self):
        with pytest.raises(ValueError) as exc:
            parse_param_flags(["=revenue"])
        assert str(exc.value) == (
            "--param =revenue: expected key=value, e.g. --param metric=revenue."
        )


# ─── Coercion ─────────────────────────────────────────────────────


class TestCoercion:
    def test_number_coerces_to_int(self, load):
        ps = load(top_n="25")
        assert ps.values["top_n"] == 25
        assert isinstance(ps.values["top_n"], int)

    def test_number_coerces_to_float(self, load):
        ps = load(lo="12.5")
        assert ps.values["lo"] == 12.5
        assert isinstance(ps.values["lo"], float)

    def test_date_coerces_to_date(self, load):
        ps = load(as_of="2025-06-01")
        assert ps.values["as_of"] == dt.date(2025, 6, 1)

    def test_string_passes_through(self, load):
        ps = load(status="closed")
        assert ps.values["status"] == "closed"
        assert isinstance(ps.values["status"], str)

    def test_field_passes_through(self, load):
        ps = load(metric="arpu")
        assert ps.values["metric"] == "arpu"
        assert isinstance(ps.values["metric"], str)

    def test_null_token_clears_value(self, load):
        ps = load(region="null")
        assert ps.values["region"] is None

    def test_boolean_looking_value_stays_a_string(self):
        """There is no bool parameter type — the declared type drives coercion."""
        from shelves.params.loader import load_parameters

        declared = load_parameters(params_fixture(), models_dir=MODELS_DIR)
        assert coerce_override("status", declared["status"], "true") == "true"

    def test_numeric_looking_string_param_stays_a_string(self):
        from shelves.params.loader import load_parameters

        declared = load_parameters(params_fixture(), models_dir=MODELS_DIR)
        coerced = coerce_override("status", declared["status"], "10")
        assert coerced == "10"
        assert isinstance(coerced, str)

    def test_undeclared_name_passes_through_uncoerced(self):
        """`ParameterSet.__init__` owns the undeclared-parameter message."""
        from shelves.params.coerce import coerce_overrides
        from shelves.params.loader import load_parameters

        declared = load_parameters(params_fixture(), models_dir=MODELS_DIR)
        assert coerce_overrides(declared, {"nope": "x"}) == {"nope": "x"}


# ─── Overrides + domains ──────────────────────────────────────────


class TestOverrides:
    def test_defaults_fill_unoverridden(self, load):
        ps = load(metric="cost")
        assert ps.values["metric"] == "cost"
        assert ps.values["region"] == "EMEA"  # default
        assert ps.values["top_n"] == 10  # default
        assert ps.values["as_of"] is None  # default: null

        # SHE-90's domains came along for the ride — the builder resolved them.
        assert ps.domains["region"].values == ["APAC", "EMEA", "NA"]

    def test_override_inside_field_ref_domain_accepted(self, load):
        ps = load(region="APAC")
        assert ps.values["region"] == "APAC"

    def test_override_outside_field_ref_domain_rejected(self, load):
        with pytest.raises(ParameterDomainError) as exc:
            load(region="NOT_A_REGION")
        assert str(exc.value) == (
            "parameters.region: value 'NOT_A_REGION' is not in the domain of "
            "'orders.region'. Valid values: APAC, EMEA, NA (3 total)."
        )

    def test_no_data_skips_domain_resolution(self):
        """`--no-data` means touch no data source — including for domains."""
        ps = load_parameter_set(
            params_fixture(),
            models_dir=MODELS_DIR,
            overrides={"region": "NOT_A_REGION"},
            resolve_domains=False,
        )
        assert ps.domains == {}
        # Unchecked against the domain, but literal constraints still hold.
        assert ps.values["region"] == "NOT_A_REGION"

    def test_no_data_still_enforces_literal_constraints(self):
        with pytest.raises(ValueError) as exc:
            load_parameter_set(
                params_fixture(),
                models_dir=MODELS_DIR,
                overrides={"top_n": "99"},
                resolve_domains=False,
            )
        assert str(exc.value) == "parameters.top_n: 99 is outside the range min: 5, max: 50"


# ─── File location ────────────────────────────────────────────────


class TestFileLocation:
    def test_explicit_parameters_file(self, tmp_path: Path):
        custom = tmp_path / "custom.yaml"
        custom.write_text(_ONE_PARAM_FILE)

        # No data_base_dir, deliberately: a `type: field` parameter's values are
        # field NAMES, checked against the manifest — no data access at all.
        ps = load_parameter_set(custom, models_dir=MODELS_DIR)
        assert set(ps.declared) == {"metric"}
        assert ps.values["metric"] == "cost"
        assert ps.domains == {}

    def test_default_path_from_models_dir(self):
        ps = load_parameter_set(None, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        assert "metric" in ps.declared  # found tests/fixtures/models/parameters.yaml

    def test_missing_data_base_dir_surfaces_domain_error(self, tmp_path: Path, monkeypatch):
        # Pin the CWD: the failure depends on data/orders.json being absent from
        # it, and asserting that about the repo root would pass for the wrong
        # reason.
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ParameterDomainError, match="data file for model 'orders' not found"):
            load_parameter_set(None, models_dir=MODELS_DIR)

    def test_missing_file_is_empty_set(self, tmp_path: Path):
        ps = load_parameter_set(None, models_dir=tmp_path)  # empty dir
        assert ps.declared == {}
        assert ps.values == {}

    def test_missing_explicit_file_is_empty_set(self, tmp_path: Path):
        ps = load_parameter_set(tmp_path / "nope.yaml", models_dir=MODELS_DIR)
        assert ps.declared == {}
        assert ps.values == {}


# ─── Coercion / validation errors ─────────────────────────────────


class TestCoercionErrors:
    # C1
    def test_uncoercible_number(self, load):
        with pytest.raises(ValueError) as exc:
            load(top_n="abc")
        assert str(exc.value) == (
            "parameters.top_n: 'abc' is not a number. Give a number between 5 and 50."
        )

    # C2
    def test_uncoercible_date(self, load):
        with pytest.raises(ValueError) as exc:
            load(as_of="June 1st")
        assert str(exc.value) == (
            "parameters.as_of: 'June 1st' is not a date. Use ISO format, e.g. "
            "2024-01-31. Give a date between 2024-01-01 and 2026-12-31."
        )

    # C3
    def test_number_out_of_range(self, load):
        with pytest.raises(ValueError) as exc:
            load(top_n="99")
        assert str(exc.value) == "parameters.top_n: 99 is outside the range min: 5, max: 50"

    # C4
    def test_value_outside_enumerated_values(self, load):
        with pytest.raises(ValueError) as exc:
            load(status="archived")
        assert str(exc.value) == (
            "parameters.status: 'archived' is not in values ['open', 'closed', 'pending']"
        )

    # C4, empty is not a synonym for null
    def test_empty_value_is_rejected(self, load):
        with pytest.raises(ValueError) as exc:
            load(status="")
        assert str(exc.value) == (
            "parameters.status: '' is not in values ['open', 'closed', 'pending']"
        )

    # C5
    def test_field_not_in_values(self, load):
        with pytest.raises(ValueError) as exc:
            load(metric="profit")
        assert str(exc.value) == (
            "parameters.metric: 'profit' is not in values ['revenue', 'cost', 'arpu']"
        )

    # C6
    def test_undeclared_name(self, load):
        with pytest.raises(ValueError) as exc:
            load(nope="x")
        assert str(exc.value) == (
            "'nope' is not a declared parameter. Declared in parameters.yaml: "
            "as_of, hi, lo, maybe_region, metric, region, status, top_n, week_grain."
        )

    # C7
    def test_null_on_a_field_parameter(self, load):
        with pytest.raises(ValueError) as exc:
            load(metric="null")
        assert str(exc.value) == (
            "parameters.metric: type 'field' requires a non-null value — a shelf cannot be empty."
        )

    # C8
    def test_date_out_of_bounds_reads_as_iso(self, load):
        with pytest.raises(ValueError) as exc:
            load(as_of="2030-01-01")
        assert str(exc.value) == (
            "parameters.as_of: 2030-01-01 is outside the range min: 2024-01-01, max: 2026-12-31"
        )

    # C11
    def test_value_outside_resolved_field_ref_domain(self, load):
        with pytest.raises(ParameterDomainError) as exc:
            load(region="LATAM")
        assert str(exc.value) == (
            "parameters.region: value 'LATAM' is not in the domain of 'orders.region'. "
            "Valid values: APAC, EMEA, NA (3 total)."
        )

    # C11, the surface-level contract
    def test_domain_error_is_a_value_error(self, load):
        with pytest.raises(ValueError):
            load(region="LATAM")

    # C12
    def test_parameters_file_names_an_unknown_field(self):
        with pytest.raises(ValueError, match="is not a field in model 'orders'"):
            load_parameter_set(
                params_fixture("parameters_invalid_unknown_field.yaml"),
                models_dir=MODELS_DIR,
            )

    # C12, sibling
    def test_parameters_file_names_an_unknown_model(self):
        with pytest.raises(ValueError, match="model 'nope' not found"):
            load_parameter_set(
                params_fixture("parameters_invalid_unknown_model.yaml"),
                models_dir=MODELS_DIR,
            )


# ─── Render CLI ───────────────────────────────────────────────────


def _vl_from_html(html: str) -> dict:
    """Extract the embedded Vega-Lite spec from standalone rendered HTML."""
    import json
    import re

    m = re.search(r"const spec = (\{.*?\});", html, re.DOTALL)
    assert m is not None, "embedded vega-lite spec not found"
    return json.loads(m.group(1))


class TestRenderCLI:
    def test_param_applies_to_a_chart(self, tmp_path: Path, monkeypatch):
        import shelves.cli.render as render

        out = tmp_path / "chart.html"
        monkeypatch.setattr(
            "sys.argv",
            [
                "shelves-render",
                str(YAML_DIR / "param_field_swap.yaml"),
                "--models-dir",
                str(MODELS_DIR),
                "--data-dir",
                str(FIXTURES_DIR),
                "--no-theme",
                "--param",
                "metric=cost",
                "--out",
                str(out),
            ],
        )
        render.main()
        vl = _vl_from_html(out.read_text())
        assert vl["encoding"]["y"]["field"] == "cost"

    def test_param_applies_to_every_sheet_of_a_dashboard(self, tmp_path: Path, monkeypatch):
        import shelves.cli.render as render
        from tests.conftest import LAYOUT_DIR

        out = tmp_path / "dash.html"
        monkeypatch.setattr(
            "sys.argv",
            [
                "shelves-render",
                str(LAYOUT_DIR / "param_dashboard.yaml"),
                "--chart-dir",
                str(YAML_DIR),
                "--models-dir",
                str(MODELS_DIR),
                "--data-dir",
                str(FIXTURES_DIR),
                "--no-theme",
                "--param",
                "metric=arpu",
                "--out",
                str(out),
            ],
        )
        render.main()
        html = out.read_text()
        import json
        import re

        m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert m is not None
        specs = json.loads(m.group(1))
        # Keys are rendered DOM ids: sheet-<name>.
        assert specs["sheet-swap_a"]["encoding"]["y"]["field"] == "arpu"
        assert specs["sheet-swap_b"]["encoding"]["y"]["field"] == "arpu"

    def test_no_data_renders_without_resolving_domains(self, tmp_path: Path, monkeypatch):
        """--no-data means no data access — so no --data-dir is needed either."""
        import shelves.cli.render as render

        out = tmp_path / "chart.html"
        monkeypatch.chdir(tmp_path)  # no data/orders.json here
        monkeypatch.setattr(
            "sys.argv",
            [
                "shelves-render",
                str(YAML_DIR / "param_field_swap.yaml"),
                "--models-dir",
                str(MODELS_DIR),
                "--no-data",
                "--no-theme",
                "--param",
                "metric=cost",
                "--out",
                str(out),
            ],
        )
        render.main()
        vl = _vl_from_html(out.read_text())
        assert vl["encoding"]["y"]["field"] == "cost"
        assert "data" not in vl

    def test_data_dir_resolves_chart_inline_source(self, tmp_path: Path, monkeypatch):
        """--data-dir was a dashboards-only flag; the chart branch honors it now."""
        import shelves.cli.render as render

        out = tmp_path / "chart.html"
        monkeypatch.chdir(tmp_path)  # data/orders.json is NOT here
        monkeypatch.setattr(
            "sys.argv",
            [
                "shelves-render",
                str(YAML_DIR / "simple_bar.yaml"),
                "--models-dir",
                str(MODELS_DIR),
                "--data-dir",
                str(FIXTURES_DIR),
                "--no-theme",
                "--out",
                str(out),
            ],
        )
        render.main()
        vl = _vl_from_html(out.read_text())
        assert len(vl["data"]["values"]) > 0


class TestRenderCLIErrors:
    # C10
    def test_bad_param_exits_two(self, tmp_path: Path, monkeypatch, capsys):
        import shelves.cli.render as render

        monkeypatch.setattr(
            "sys.argv",
            [
                "shelves-render",
                str(YAML_DIR / "param_field_swap.yaml"),
                "--models-dir",
                str(MODELS_DIR),
                "--data-dir",
                str(FIXTURES_DIR),
                "--no-theme",
                "--param",
                "nope=x",
                "--out",
                str(tmp_path / "chart.html"),
            ],
        )
        with pytest.raises(SystemExit) as exc:
            render.main()
        assert exc.value.code == 2
        assert "is not a declared parameter" in capsys.readouterr().err

    def test_malformed_param_syntax_exits_two(self, tmp_path: Path, monkeypatch, capsys):
        import shelves.cli.render as render

        monkeypatch.setattr(
            "sys.argv",
            [
                "shelves-render",
                str(YAML_DIR / "param_field_swap.yaml"),
                "--models-dir",
                str(MODELS_DIR),
                "--data-dir",
                str(FIXTURES_DIR),
                "--no-theme",
                "--param",
                "metric",
                "--out",
                str(tmp_path / "chart.html"),
            ],
        )
        with pytest.raises(SystemExit) as exc:
            render.main()
        assert exc.value.code == 2
        assert "expected key=value" in capsys.readouterr().err

    def test_broken_parameters_file_exits_two(self, tmp_path: Path, monkeypatch, capsys):
        import shelves.cli.render as render

        monkeypatch.setattr(
            "sys.argv",
            [
                "shelves-render",
                str(YAML_DIR / "simple_bar.yaml"),
                "--models-dir",
                str(MODELS_DIR),
                "--parameters-file",
                str(params_fixture("parameters_broken.yaml")),
                "--no-theme",
                "--out",
                str(tmp_path / "chart.html"),
            ],
        )
        with pytest.raises(SystemExit) as exc:
            render.main()
        assert exc.value.code == 2
        assert "type 'field' needs field references, not literal values." in (
            capsys.readouterr().err
        )


class TestDevCLI:
    """The dev CLI rebuilds the set inside _build() on every rebuild.

    Two consequences, both wanted: fixing a broken parameters.yaml takes effect
    on the next save, and a broken one shows in the Build Error page instead of
    crashing the server at launch.
    """

    def _build(self, tmp_path: Path, **kwargs):
        from shelves.cli import dev

        state = dev._State()
        dev._build(
            kwargs.pop("yaml_path", YAML_DIR / "param_field_swap.yaml"),
            None,  # data_path
            True,  # no_theme
            None,  # theme_path
            state,
            data_dir=FIXTURES_DIR,
            models_dir=MODELS_DIR,
            **kwargs,
        )
        return state.html

    def test_build_applies_param_override(self, tmp_path: Path):
        html = self._build(
            tmp_path,
            parameters_path=params_fixture(),
            param_overrides={"metric": "cost"},
        )
        assert "Build Error" not in html
        assert _vl_from_html(html)["encoding"]["y"]["field"] == "cost"

    def test_build_applies_declared_default(self, tmp_path: Path):
        html = self._build(tmp_path, parameters_path=params_fixture())
        assert _vl_from_html(html)["encoding"]["y"]["field"] == "revenue"  # default

    def test_build_chart_honors_models_dir_and_data_dir(self, tmp_path: Path):
        """The dev chart branch reads --models-dir/--data-dir (SHE-91 coherence fix).

        Without this the set is built from one model universe and the chart
        compiled against another.
        """
        html = self._build(
            tmp_path,
            yaml_path=YAML_DIR / "simple_bar.yaml",
            parameters_path=params_fixture(),
        )
        vl = _vl_from_html(html)
        assert vl["encoding"]["y"]["title"] == "Revenue"  # from fixtures orders.yaml
        assert len(vl["data"]["values"]) > 0  # rows resolved via data_dir

    def test_broken_parameters_file_shows_in_the_error_page(self, tmp_path: Path):
        html = self._build(tmp_path, parameters_path=params_fixture("parameters_broken.yaml"))
        assert "Build Error" in html
        assert "type &#x27;field&#x27; needs field references" in html or (
            "type 'field' needs field references" in html
        )

    def test_undeclared_override_shows_in_the_error_page(self, tmp_path: Path):
        html = self._build(
            tmp_path,
            parameters_path=params_fixture(),
            param_overrides={"nope": "x"},
        )
        assert "Build Error" in html
        assert "is not a declared parameter" in html


# `--data` keeps working alongside parameters (the flag reads rows directly).
class TestRenderCLIDataFlag:
    def test_explicit_data_flag_with_param(self, tmp_path: Path, monkeypatch):
        import shelves.cli.render as render

        out = tmp_path / "chart.html"
        monkeypatch.setattr(
            "sys.argv",
            [
                "shelves-render",
                str(YAML_DIR / "param_field_swap.yaml"),
                "--models-dir",
                str(MODELS_DIR),
                "--data-dir",
                str(FIXTURES_DIR),
                "--data",
                str(DATA_DIR / "orders.json"),
                "--no-theme",
                "--param",
                "metric=cost",
                "--out",
                str(out),
            ],
        )
        render.main()
        vl = _vl_from_html(out.read_text())
        assert vl["encoding"]["y"]["field"] == "cost"
        assert len(vl["data"]["values"]) > 0


# ─── Missing explicit parameters file warning ──────────────────────


class TestMissingParametersFileWarning:
    def test_render_cli_warns_on_missing_explicit_file(self, capsys, monkeypatch, tmp_path):
        import shelves.cli.render as render

        chart = tmp_path / "chart.yaml"
        chart.write_text("sheet: T\ndata: inline\ncols: a\nrows: b\nmarks: bar\n")
        out = tmp_path / "chart.html"
        monkeypatch.setattr(
            "sys.argv",
            [
                "shelves-render",
                str(chart),
                "--no-data",
                "--no-theme",
                "--parameters-file",
                str(tmp_path / "nonexistent.yaml"),
                "--out",
                str(out),
            ],
        )
        with contextlib.suppress(SystemExit, Exception):
            render.main()
        assert "not found" in capsys.readouterr().err

    def test_default_missing_path_does_not_warn(self, tmp_path):
        ps = load_parameter_set(None, models_dir=tmp_path)
        assert ps.declared == {}
