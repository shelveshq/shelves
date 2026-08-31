from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from shelves.studio.connection import ConnectionManager


def _build_scope_dirs(
    charts_dir: Path,
    dashboards_dir: Path,
    models_dir: Path,
    assets_dir: Path,
    theme_path: Path | None,
) -> list[Path]:
    """Watcher event-filter scope: the configured dirs + the theme file.

    watch_project's filter accepts files as well as dirs (is_relative_to
    matches the file itself). An outside-project theme never matches —
    the watch is rooted at project_dir — which is the documented limitation:
    external edits to an outside theme don't live-reload; Studio saves to it
    still do (PUT /file broadcasts theme_changed directly).
    """
    scope = [charts_dir, dashboards_dir, models_dir, assets_dir]
    if theme_path is not None:
        scope.append(theme_path)
    return scope


async def handle_fs_event(
    event: str,
    abs_path: Path,
    *,
    manager: ConnectionManager,
    project_dir: Path,
    theme_path: Path | None,
    models_dir: Path,
    charts_dir: Path,
    parameters_path: Path | None = None,
) -> None:
    """Watcher callback body — module-level so the routing is testable.

    file_change always broadcasts; a theme event additionally broadcasts
    theme_changed and never attempts a compile (theme YAML has no
    sheet/dashboard key); everything else keeps the existing compile routing.
    """
    from shelves.studio.watcher import should_compile

    try:
        rel = str(abs_path.relative_to(project_dir))
    except ValueError:
        rel = abs_path.name

    await manager.broadcast({"type": "file_change", "event": event, "path": rel})

    if theme_path is not None and abs_path.resolve() == theme_path.resolve():
        await manager.broadcast({"type": "theme_changed", "path": rel})
        return

    if parameters_path is not None and abs_path.resolve() == parameters_path.resolve():
        await manager.broadcast({"type": "parameters_changed", "path": rel})
        return

    if abs_path.resolve().is_relative_to(models_dir.resolve()):
        from shelves.data.domains import clear_domain_cache

        clear_domain_cache()

    if should_compile(abs_path) and event != "deleted":
        await compile_file_and_broadcast(
            abs_path,
            rel,
            manager,
            models_dir,
            theme_path,
            project_dir=project_dir,
            charts_dir=charts_dir,
            parameters_path=parameters_path,
        )


def make_lifespan(
    project_dir: Path,
    theme_path: Path | None,
    models_dir: Path,
    charts_dir: Path,
    dashboards_dir: Path,
    assets_dir: Path,
    parameters_path: Path | None = None,
):
    """
    Create a FastAPI lifespan context manager that starts/stops the file watcher.
    """
    from shelves.studio.watcher import watch_project

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager: ConnectionManager = app.state.manager
        stop_event = asyncio.Event()

        async def on_change(event: str, abs_path: Path) -> None:
            await handle_fs_event(
                event,
                abs_path,
                manager=manager,
                project_dir=project_dir,
                theme_path=theme_path,
                models_dir=models_dir,
                charts_dir=charts_dir,
                parameters_path=parameters_path,
            )

        # Broadcasts are scoped to the configured dirs + the theme file
        # (SHE-39/SHE-44); the watch itself is rooted at project_dir so dirs
        # created after startup stay live.
        scope_dirs = _build_scope_dirs(
            charts_dir, dashboards_dir, models_dir, assets_dir, theme_path
        )
        task = asyncio.create_task(watch_project(project_dir, scope_dirs, on_change, stop_event))
        try:
            yield
        finally:
            stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return lifespan


async def compile_file_and_broadcast(
    abs_path: Path,
    rel: str,
    manager: ConnectionManager,
    models_dir: Path,
    theme_path: Path | None,
    project_dir: Path | None = None,
    charts_dir: Path | None = None,
    parameters_path: Path | None = None,
) -> None:
    """Read a YAML file, compile it, and broadcast the result."""
    import yaml as _yaml
    from pydantic import ValidationError as _ValidationError

    from shelves.diagnostics import capture_structured_warnings
    from shelves.params.resolve import load_parameter_set
    from shelves.pipeline import compile_chart, resolve_model_data
    from shelves.studio.routes.compile import _format_warnings

    try:
        try:
            content = abs_path.read_text()
        except FileNotFoundError:
            # The file was created and deleted before we could read it (a test
            # temp file, or an editor's atomic-save swap file). The watcher
            # already saw the create; treat the read race as a silent no-op
            # rather than surfacing a spurious "No such file" compile error.
            return
        if not content.strip():
            await manager.broadcast(
                {
                    "type": "compile_result",
                    "path": rel,
                    "vega_lite_spec": None,
                    "errors": ["Empty YAML body"],
                    "warnings": [],
                    "model": None,
                }
            )
            return

        # Route dashboard YAML to the dashboard pipeline
        raw = _yaml.safe_load(content)
        if isinstance(raw, dict) and "dashboard" in raw:
            await compile_dashboard_file_and_broadcast(
                abs_path,
                rel,
                manager,
                models_dir,
                theme_path,
                project_dir=project_dir,
                charts_dir=charts_dir,
                parameters_path=parameters_path,
            )
            return

        # Skip non-chart YAML (e.g. models)
        if not isinstance(raw, dict) or "sheet" not in raw:
            return

        # Capture Python warnings (KPI shelf conflicts, tooltip disaggregation,
        # ...) into the structured warnings list the frontend displays —
        # positioned exactly like the POST /compile route so the same chart
        # yields the same inline markers whether you type it or save it.
        raw_warnings: list[dict] = []
        effective_models_dir = models_dir if models_dir.exists() else None
        with capture_structured_warnings(raw_warnings):
            parameters = load_parameter_set(
                parameters_path,
                models_dir=effective_models_dir,
                data_base_dir=project_dir,
            )
            vl_spec, spec = compile_chart(
                content,
                theme_path=theme_path,
                models_dir=effective_models_dir,
                parameters=parameters,
            )

        try:
            with capture_structured_warnings(raw_warnings):
                vl_spec = resolve_model_data(
                    vl_spec,
                    spec,
                    models_dir=models_dir,
                    data_base_dir=project_dir,
                    parameters=parameters,
                )
        except Exception as e:
            raw_warnings.append({"msg": f"Data resolution skipped: {e}", "loc": None, "code": None})

        await manager.broadcast(
            {
                "type": "compile_result",
                "path": rel,
                "vega_lite_spec": vl_spec,
                "errors": [],
                "warnings": _format_warnings(raw_warnings, content),
                "model": spec.data,
            }
        )
    except _ValidationError as e:
        from shelves.studio.routes.compile import _format_validation_errors

        await manager.broadcast(
            {
                "type": "compile_result",
                "path": rel,
                "vega_lite_spec": None,
                "errors": _format_validation_errors(e, content),
                "warnings": [],
                "model": None,
            }
        )
    except _yaml.YAMLError as e:
        from shelves.studio.routes.compile import _format_yaml_error

        await manager.broadcast(
            {
                "type": "compile_result",
                "path": rel,
                "vega_lite_spec": None,
                "errors": [_format_yaml_error(e)],
                "warnings": [],
                "model": None,
            }
        )
    except Exception as e:
        # Same structured dict shape as POST /compile's runtime-error path, so
        # every consumer (markers, overlay, status counts) renders uniformly.
        await manager.broadcast(
            {
                "type": "compile_result",
                "path": rel,
                "vega_lite_spec": None,
                "errors": [
                    {
                        "loc": [],
                        "display_loc": [],
                        "msg": str(e),
                        "friendly_msg": str(e),
                        "source": "runtime",
                        "type": "runtime_error",
                        "line": None,
                        "col": None,
                    }
                ],
                "warnings": [],
                "model": None,
            }
        )


async def compile_dashboard_file_and_broadcast(
    abs_path: Path,
    rel: str,
    manager: ConnectionManager,
    models_dir: Path,
    theme_path: Path | None,
    project_dir: Path | None = None,
    charts_dir: Path | None = None,
    parameters_path: Path | None = None,
) -> None:
    """Read a dashboard YAML file, compile it, and broadcast the result."""
    from shelves.studio.routes.dashboard import run_dashboard_pipeline

    try:
        try:
            content = abs_path.read_text()
        except FileNotFoundError:
            # Created-then-deleted before read (test temp / atomic-save swap);
            # the read race is a silent no-op, not a dashboard compile error.
            return
        effective_project_dir = project_dir or abs_path.parent
        resolved_charts = charts_dir or (effective_project_dir / "charts")
        result = await run_dashboard_pipeline(
            content,
            effective_project_dir,
            resolved_charts,
            theme_path,
            models_dir=models_dir,
            parameters_path=parameters_path,
        )
        await manager.broadcast(
            {
                "type": "dashboard_compile_result",
                "path": rel,
                **result,
            }
        )
    except Exception as e:
        from shelves.studio.routes._diagnostics import runtime_error_item

        # Structured (not a bare string) so applyCompileMarkers renders a marker
        # for it — the marker pass drops string errors silently (SHE-105).
        await manager.broadcast(
            {
                "type": "dashboard_compile_result",
                "path": rel,
                "html": None,
                "errors": [runtime_error_item(str(e))],
                "warnings": [],
                "component_tree": [],
            }
        )
