"""
Parameter Surface Tests (SHE-91)

Two things are proved here.

**Threading** — a `ParameterSet` built once by a surface reaches every chart it
compiles, with its values still typed (a coerced `20` stays the number 20 in a
`between` filter, not the string "20").

**Parity** — the `surface-parity` deliverable. Four surfaces (render CLI, dev
CLI, Studio chart compile, Studio dashboard compile), one project, one assertion
set. In SHE-91 the two Studio surfaces have no override input — `--param` is a
CLI flag and URL-serialized state is SHE-92 — so the four-surface parity is over
*declared-parameter resolution and error reporting*, and override-specific
parity is asserted across the two CLI surfaces.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from shelves.models.loader import clear_model_cache
from shelves.params.coerce import parse_param_flags
from shelves.params.resolve import load_parameter_set
from shelves.pipeline import compile_chart
from tests.conftest import (
    DATA_DIR,
    FIXTURES_DIR,
    LAYOUT_DIR,
    MODELS_DIR,
    YAML_DIR,
    load_yaml,
    params_fixture,
)
from tests.conftest import LoopbackTestClient as TestClient


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_model_cache()
    yield
    clear_model_cache()


def _maybe_embedded_specs(html: str) -> dict | None:
    """The `const specs = {...};` block, or None when the HTML has none.

    A dashboard whose every sheet failed to compile emits no specs block at all
    — not an empty one — so the surface runners must tolerate its absence.
    Keys are the rendered DOM ids: `sheet-<name>`, not the bare sheet name.
    """
    m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
    return json.loads(m.group(1)) if m else None


def _embedded_specs(html: str) -> dict:
    """`_maybe_embedded_specs`, asserting the block is present."""
    specs = _maybe_embedded_specs(html)
    assert specs is not None, "embedded specs block not found"
    return specs


def _sheet_y_field(specs: dict, name: str) -> str:
    """The y-encoding field of one sheet in an embedded specs block."""
    return specs[f"sheet-{name}"]["encoding"]["y"]["field"]


def _vl_from_html(html: str) -> dict:
    """Extract the embedded Vega-Lite spec from standalone rendered HTML."""
    m = re.search(r"const spec = (\{.*?\});", html, re.DOTALL)
    assert m is not None, "embedded vega-lite spec not found"
    return json.loads(m.group(1))


# ─── The shared test project ──────────────────────────────────────

# Only `metric`, and only explicit field entries. Two reasons not to copy
# tests/fixtures/models/parameters.yaml: its three field-reference domains would
# make this gate depend on data (so every parity failure would have two possible
# causes), and the "Declared in ..." list stays short and stable, which Parity
# Test 2 asserts on. `default: cost` rather than `revenue` matters — `revenue` is
# the y field of several unrelated fixtures, so `cost` proves the value came from
# the parameters file rather than from a coincidence.
_PROJECT_PARAMETERS = """\
parameters:
  metric:
    type: field
    values:
      - model: orders
        field: revenue
      - model: orders
        field: cost
      - model: orders
        field: arpu
    default: cost
"""

# `type: field` with LITERAL entries → E1 from SHE-89.
_BROKEN_PARAMETERS = """\
parameters:
  metric:
    type: field
    values:
      - revenue
      - cost
    default: revenue
"""


def _param_project(tmp_path: Path, parameters: str = _PROJECT_PARAMETERS) -> Path:
    """Build the one project all four surfaces are pointed at."""
    (tmp_path / "models").mkdir()
    shutil.copy(MODELS_DIR / "orders.yaml", tmp_path / "models" / "orders.yaml")
    (tmp_path / "models" / "parameters.yaml").write_text(parameters)

    (tmp_path / "charts").mkdir()
    shutil.copy(YAML_DIR / "param_field_swap.yaml", tmp_path / "charts" / "swap.yaml")
    shutil.copy(YAML_DIR / "param_undeclared_ref.yaml", tmp_path / "charts" / "bad_ref.yaml")

    (tmp_path / "dashboards").mkdir()
    for name, link in (("dash.yaml", "swap.yaml"), ("dash_bad.yaml", "bad_ref.yaml")):
        (tmp_path / "dashboards" / name).write_text(
            LAYOUT_DIR.joinpath("param_dashboard.yaml")
            .read_text()
            .replace("param_field_swap.yaml", link)
        )

    # Each runner also gets a data base dir so the compiled charts get their
    # rows — the assertions read the y FIELD, not the data, but a runner that
    # cannot find orders.json emits a data warning that muddies failure output.
    (tmp_path / "data").mkdir()
    shutil.copy(DATA_DIR / "orders.json", tmp_path / "data" / "orders.json")
    return tmp_path


_WRAPPERS = (
    # compile_dashboard_charts, fail_fast=False (Studio) and True (CLI).
    re.compile(r"^Chart '[^']*' \([^)]*\): "),
    re.compile(r"^Failed to compile chart for sheet '[^']*' \(link: [^)]*\): "),
    re.compile(r"^Error: "),  # the render CLI's stderr prefix
)

# The parameters path appears verbatim in loader errors, and the surfaces spell
# it differently: `load_parameters` resolves its DEFAULT path (`/private/var/…`
# on macOS) while Studio stores `<models_dir>/parameters.yaml` as given
# (`/var/…`). That is a path-spelling difference, not a message difference, so
# parity is asserted over the text with the path collapsed.
_PARAMS_PATH_RE = re.compile(r"\S*parameters\.yaml")


def _normalize(message: str) -> str:
    """Strip the known per-surface wrappers so four messages can be compared."""
    out = message.strip()
    for pattern in _WRAPPERS:
        out = pattern.sub("", out)
    return _PARAMS_PATH_RE.sub("<parameters.yaml>", out)


# ─── Surface runners — each returns (y_field | None, error | None) ─


def _run_render_cli(
    project: Path, target: str, extra_argv: list[str]
) -> tuple[str | None, str | None]:
    """shelves-render: monkeypatch argv, call main(), read the output HTML."""
    import shelves.cli.render as render

    out = project / "out.html"
    argv = [
        "shelves-render",
        str(project / target),
        "--models-dir",
        str(project / "models"),
        "--data-dir",
        str(project),
        "--chart-dir",
        str(project / "charts"),
        "--no-theme",
        "--out",
        str(out),
        *extra_argv,
    ]
    stderr = io.StringIO()
    try:
        with patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
            render.main()
    except SystemExit:
        # A correctable error: main() printed to stderr and exited 2.
        return None, stderr.getvalue().strip()
    except (ValueError, RuntimeError) as e:
        # A $ref failure surfaces from compile_chart / compose_dashboard, which
        # main() does not wrap — the message is what parity is about.
        return None, str(e)

    html = out.read_text()
    if "const specs = " in html:  # dashboard
        specs = _embedded_specs(html)
        return (_sheet_y_field(specs, "swap_a") if specs else None), None
    return _vl_from_html(html)["encoding"]["y"]["field"], None


def _run_dev_cli(
    project: Path, target: str, extra_argv: list[str]
) -> tuple[str | None, str | None]:
    """shelves-dev: call _build() directly with a _State, then read state.html.

    _build never raises — errors land in the Build Error page, so the message is
    extracted from the <pre> block. Flags are parsed through the real
    build_parser so this runner exercises the same threading main() does.
    """
    import shelves.cli.dev as dev

    args = dev.build_parser().parse_args([str(project / target), *extra_argv])
    state = dev._State()
    dev._build(
        Path(args.yaml_path),
        None,  # data_path
        True,  # no_theme
        None,  # theme_path
        state,
        project / "charts",
        project,
        project / "models",
        Path(args.parameters_file) if args.parameters_file else None,
        parse_param_flags(args.param),
    )

    if "Build Error" in state.html:
        m = re.search(r"<pre>(.*?)</pre>", state.html, re.DOTALL)
        assert m is not None, "Build Error page without a <pre> block"
        return None, m.group(1).strip()

    if "const specs = " in state.html:  # dashboard
        specs = _embedded_specs(state.html)
        return (_sheet_y_field(specs, "swap_a") if specs else None), None
    return _vl_from_html(state.html)["encoding"]["y"]["field"], None


def _studio_client(project: Path) -> TestClient:
    from shelves.studio.server import create_app

    app = create_app(project_dir=project, models_dir=project / "models")
    # No `with`: the lifespan would start a filesystem watcher this test has no
    # use for. Studio clients MUST be LoopbackTestClient (Host validation, SHE-52).
    return TestClient(app, raise_server_exceptions=False)


def _run_studio_chart(
    project: Path, target: str, extra_argv: list[str] | None = None
) -> tuple[str | None, str | None]:
    """POST /compile with the chart body."""
    body = (project / target).read_text()
    data = _studio_client(project).post("/compile", content=body).json()
    if data["errors"]:
        err = data["errors"][0]
        return None, err["msg"] if isinstance(err, dict) else str(err)
    return data["vega_lite_spec"]["encoding"]["y"]["field"], None


def _run_studio_dashboard(
    project: Path, target: str, extra_argv: list[str] | None = None
) -> tuple[str | None, str | None]:
    """POST /compile-dashboard; parse `const specs = {...}` from data["html"]."""
    body = (project / target).read_text()
    data = _studio_client(project).post("/compile-dashboard", content=body).json()
    if data["errors"]:
        err = data["errors"][0]
        return None, err["msg"] if isinstance(err, dict) else str(err)

    specs = _maybe_embedded_specs(data["html"])
    if not specs:
        # fail_fast=False: a sheet that failed to compile is a warning and an
        # empty box, so the message lives in warnings, not errors.
        return None, (data["warnings"][0] if data["warnings"] else None)
    return _sheet_y_field(specs, "swap_a"), None


_ALL_SURFACES = (_run_render_cli, _run_dev_cli, _run_studio_chart, _run_studio_dashboard)


def _target_for(runner, good: bool = True) -> str:
    """The chart or dashboard path a given runner should be pointed at."""
    if runner is _run_studio_dashboard:
        return "dashboards/dash.yaml" if good else "dashboards/dash_bad.yaml"
    return "charts/swap.yaml" if good else "charts/bad_ref.yaml"


class TestFourSurfaceParity:
    """One project, one assertion set, four surfaces.

    Override-specific parity is asserted over the two CLI surfaces only: in
    SHE-91 the Studio surfaces have no override input. Do NOT invent one to
    "complete" the table — that is SHE-92.
    """

    def test_all_surfaces_apply_declared_default(self, tmp_path: Path):
        project = _param_project(tmp_path)  # metric default = "cost"
        results = [runner(project, _target_for(runner), []) for runner in _ALL_SURFACES]

        assert [r[0] for r in results] == ["cost"] * 4
        assert [r[1] for r in results] == [None] * 4

    def test_all_surfaces_same_error_for_undeclared_ref(self, tmp_path: Path):
        project = _param_project(tmp_path)
        expected = (
            "rows: $nope is not a declared parameter. Declared in models/parameters.yaml: metric."
        )

        errors = []
        for runner in _ALL_SURFACES:
            field, err = runner(project, _target_for(runner, good=False), [])
            assert field is None, f"{runner.__name__} compiled a bad $ref"
            assert err is not None, f"{runner.__name__} reported no error"
            assert expected in err, f"{runner.__name__}: {err!r}"
            errors.append(_normalize(err))

        assert len({*errors}) == 1, errors

    def test_all_surfaces_same_error_for_broken_parameters_file(self, tmp_path: Path):
        project = _param_project(tmp_path, parameters=_BROKEN_PARAMETERS)
        expected = "type 'field' needs field references, not literal values."

        errors = []
        for runner in _ALL_SURFACES:
            field, err = runner(project, _target_for(runner), [])
            assert field is None, f"{runner.__name__} compiled with a broken file"
            assert err is not None, f"{runner.__name__} reported no error"
            assert expected in err, f"{runner.__name__}: {err!r}"
            errors.append(_normalize(err))

        assert len({*errors}) == 1, errors

    def test_cli_surfaces_agree_on_param_override(self, tmp_path: Path):
        project = _param_project(tmp_path)
        for runner in (_run_render_cli, _run_dev_cli):
            result = runner(project, "charts/swap.yaml", ["--param", "metric=arpu"])
            assert result == ("arpu", None), f"{runner.__name__}: {result!r}"

    def test_cli_surfaces_agree_on_undeclared_param_error(self, tmp_path: Path):
        project = _param_project(tmp_path)
        expected = "'nope' is not a declared parameter. Declared in parameters.yaml: metric."

        errors = []
        for runner in (_run_render_cli, _run_dev_cli):
            field, err = runner(project, "charts/swap.yaml", ["--param", "nope=x"])
            assert field is None
            assert err is not None
            assert expected in err, f"{runner.__name__}: {err!r}"
            errors.append(_normalize(err))

        assert len({*errors}) == 1, errors

    def test_cli_surfaces_agree_on_dashboard_override(self, tmp_path: Path):
        """--param on a dashboard applies to every sheet — the headline example."""
        project = _param_project(tmp_path)
        for runner in (_run_render_cli, _run_dev_cli):
            result = runner(project, "dashboards/dash.yaml", ["--param", "metric=arpu"])
            assert result == ("arpu", None), f"{runner.__name__}: {result!r}"


class TestStudioReReadsPerCompile:
    """app.state holds the PATH, never a built set — Studio is long-running."""

    def test_studio_rereads_parameters_file_per_compile(self, tmp_path: Path):
        project = _param_project(tmp_path)
        params_file = project / "models" / "parameters.yaml"
        body = (project / "charts" / "swap.yaml").read_text()
        client = _studio_client(project)

        first = client.post("/compile", content=body).json()
        assert first["vega_lite_spec"]["encoding"]["y"]["field"] == "cost"

        params_file.write_text(_PROJECT_PARAMETERS.replace("default: cost", "default: arpu"))

        second = client.post("/compile", content=body).json()
        assert second["errors"] == [], second["errors"]
        assert second["vega_lite_spec"]["encoding"]["y"]["field"] == "arpu"


class TestThreading:
    def test_number_override_in_between_filter(self):
        """A coerced override keeps its type all the way into the transform."""
        ps = load_parameter_set(
            params_fixture(),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
            overrides={"lo": "20", "hi": "80"},
        )
        vl, _ = compile_chart(
            load_yaml("param_range_bounds.yaml"),
            no_theme=True,
            models_dir=MODELS_DIR,
            parameters=ps,
        )
        tx = vl["transform"][0]["filter"]
        assert tx["field"] == "margin_pct"
        assert tx["range"] == [20, 80]
        assert '"20"' not in json.dumps(tx)  # not stringified

    def test_compose_dashboard_applies_override_to_every_sheet(self):
        from shelves.compose.dashboard import compose_dashboard

        html = compose_dashboard(
            dashboard_path=LAYOUT_DIR / "param_dashboard.yaml",
            chart_base_dir=YAML_DIR,
            data_dir=FIXTURES_DIR,
            models_dir=MODELS_DIR,
            no_theme=True,
            parameters=load_parameter_set(
                params_fixture(),
                models_dir=MODELS_DIR,
                data_base_dir=FIXTURES_DIR,
                overrides={"metric": "arpu"},
            ),
        )
        specs = _embedded_specs(html)
        assert _sheet_y_field(specs, "swap_a") == "arpu"
        assert _sheet_y_field(specs, "swap_b") == "arpu"

    def test_compose_dashboard_without_parameters_still_fails_on_a_ref(self):
        """No parameters threaded → the $ref is undeclared, per SHE-89."""
        from shelves.compose.dashboard import compose_dashboard

        with pytest.raises(RuntimeError, match="is not a declared parameter"):
            compose_dashboard(
                dashboard_path=LAYOUT_DIR / "param_dashboard.yaml",
                chart_base_dir=YAML_DIR,
                data_dir=DATA_DIR,
                models_dir=MODELS_DIR,
                no_theme=True,
            )

    def test_compile_dashboard_charts_takes_the_set_it_is_given(self):
        """The loop never builds a set — one per dashboard, from the surface."""
        from shelves.compose.dashboard import compile_dashboard_charts
        from shelves.theme.theme_schema import ThemeSpec

        ps = load_parameter_set(
            params_fixture(),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
            overrides={"metric": "cost"},
        )
        specs, resolvers, warnings = compile_dashboard_charts(
            {"a": "param_field_swap.yaml", "b": "param_field_swap.yaml"},
            YAML_DIR,
            ThemeSpec(),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
            no_theme=True,
            fail_fast=True,
            parameters=ps,
        )
        assert specs["a"]["encoding"]["y"]["field"] == "cost"
        assert specs["b"]["encoding"]["y"]["field"] == "cost"
        assert set(resolvers) == {"a", "b"}
        assert warnings == []


class TestStudioWatcherSurfaces:
    """The watcher is the OTHER half of each Studio surface.

    `surface-parity` (surface map): the HTTP route fires on editor keystrokes,
    the `lifespan.py` callback fires on external file edits. A fix applied to the
    route but not the watcher is half a fix — so both broadcast helpers get the
    same parameter threading, and both are asserted here.
    """

    @staticmethod
    def _broadcast(coro_factory) -> list[dict]:
        import asyncio

        captured: list[dict] = []

        class _Capture:
            async def broadcast(self, msg: dict) -> None:
                captured.append(msg)

        asyncio.run(coro_factory(_Capture()))
        assert captured, "no broadcast emitted"
        return captured

    def test_chart_watcher_broadcast_applies_declared_default(self, tmp_path: Path):
        from shelves.studio.lifespan import compile_file_and_broadcast

        project = _param_project(tmp_path)
        chart = project / "charts" / "swap.yaml"

        captured = self._broadcast(
            lambda mgr: compile_file_and_broadcast(
                chart,
                "charts/swap.yaml",
                mgr,  # type: ignore[arg-type]
                project / "models",
                None,
                project_dir=project,
                parameters_path=project / "models" / "parameters.yaml",
            )
        )
        msg = captured[-1]
        assert msg["errors"] == [], msg["errors"]
        assert msg["vega_lite_spec"]["encoding"]["y"]["field"] == "cost"

    def test_chart_watcher_broadcast_reports_broken_parameters_file(self, tmp_path: Path):
        from shelves.studio.lifespan import compile_file_and_broadcast

        project = _param_project(tmp_path, parameters=_BROKEN_PARAMETERS)
        chart = project / "charts" / "swap.yaml"

        captured = self._broadcast(
            lambda mgr: compile_file_and_broadcast(
                chart,
                "charts/swap.yaml",
                mgr,  # type: ignore[arg-type]
                project / "models",
                None,
                project_dir=project,
                parameters_path=project / "models" / "parameters.yaml",
            )
        )
        msg = captured[-1]
        assert msg["vega_lite_spec"] is None
        # Same structured runtime_error shape the POST /compile route produces.
        err = msg["errors"][0]
        assert isinstance(err, dict)
        assert err["source"] == "runtime"
        assert err["type"] == "runtime_error"
        assert "type 'field' needs field references, not literal values." in err["msg"]

    def test_dashboard_watcher_broadcast_applies_declared_default(self, tmp_path: Path):
        from shelves.studio.lifespan import compile_dashboard_file_and_broadcast

        project = _param_project(tmp_path)
        dash = project / "dashboards" / "dash.yaml"

        captured = self._broadcast(
            lambda mgr: compile_dashboard_file_and_broadcast(
                dash,
                "dashboards/dash.yaml",
                mgr,  # type: ignore[arg-type]
                project / "models",
                None,
                project_dir=project,
                charts_dir=project / "charts",
                parameters_path=project / "models" / "parameters.yaml",
            )
        )
        msg = captured[-1]
        assert msg["errors"] == [], msg["errors"]
        specs = _embedded_specs(msg["html"])
        assert _sheet_y_field(specs, "swap_a") == "cost"
        assert _sheet_y_field(specs, "swap_b") == "cost"

    def test_dashboard_watcher_broadcast_reports_broken_parameters_file(self, tmp_path: Path):
        from shelves.studio.lifespan import compile_dashboard_file_and_broadcast

        project = _param_project(tmp_path, parameters=_BROKEN_PARAMETERS)
        dash = project / "dashboards" / "dash.yaml"

        captured = self._broadcast(
            lambda mgr: compile_dashboard_file_and_broadcast(
                dash,
                "dashboards/dash.yaml",
                mgr,  # type: ignore[arg-type]
                project / "models",
                None,
                project_dir=project,
                charts_dir=project / "charts",
                parameters_path=project / "models" / "parameters.yaml",
            )
        )
        msg = captured[-1]
        assert msg["html"] is None
        assert "type 'field' needs field references, not literal values." in msg["errors"][0]

    def test_chart_watcher_honors_a_non_default_parameters_path(self, tmp_path: Path):
        """Proves `parameters_path` is threaded, not silently defaulted.

        The default location holds `metric` → cost; a custom file elsewhere holds
        `metric` → arpu. A watcher that ignored the argument would say "cost".
        """
        from shelves.studio.lifespan import compile_file_and_broadcast

        project = _param_project(tmp_path)
        custom = project / "custom_parameters.yaml"
        custom.write_text(_PROJECT_PARAMETERS.replace("default: cost", "default: arpu"))

        captured = self._broadcast(
            lambda mgr: compile_file_and_broadcast(
                project / "charts" / "swap.yaml",
                "charts/swap.yaml",
                mgr,  # type: ignore[arg-type]
                project / "models",
                None,
                project_dir=project,
                parameters_path=custom,
            )
        )
        msg = captured[-1]
        assert msg["errors"] == [], msg["errors"]
        assert msg["vega_lite_spec"]["encoding"]["y"]["field"] == "arpu"
