from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from shelves.studio.connection import ConnectionManager


def make_lifespan(
    project_dir: Path,
    theme_path: Path | None,
    models_dir: Path,
    charts_dir: Path,
):
    """
    Create a FastAPI lifespan context manager that starts/stops the file watcher.
    """
    from shelves.studio.watcher import should_compile, watch_project

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager: ConnectionManager = app.state.manager
        stop_event = asyncio.Event()

        async def on_change(event: str, abs_path: Path) -> None:
            try:
                rel = str(abs_path.relative_to(project_dir))
            except ValueError:
                rel = abs_path.name

            await manager.broadcast({"type": "file_change", "event": event, "path": rel})

            if should_compile(abs_path) and event != "deleted":
                await compile_file_and_broadcast(
                    abs_path,
                    rel,
                    manager,
                    models_dir,
                    theme_path,
                    project_dir=project_dir,
                    charts_dir=charts_dir,
                )

        task = asyncio.create_task(watch_project(project_dir, on_change, stop_event))
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
) -> None:
    """Read a YAML file, compile it, and broadcast the result."""
    import yaml as _yaml
    from pydantic import ValidationError as _ValidationError

    from shelves.pipeline import compile_chart, resolve_model_data

    try:
        content = abs_path.read_text()
        if not content.strip():
            await manager.broadcast(
                {
                    "type": "compile_result",
                    "path": rel,
                    "vega_lite_spec": None,
                    "errors": ["Empty YAML body"],
                    "warnings": [],
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
            )
            return

        # Skip non-chart YAML (e.g. models)
        if not isinstance(raw, dict) or "sheet" not in raw:
            return

        vl_spec, spec = compile_chart(
            content,
            theme_path=theme_path,
            models_dir=models_dir if models_dir.exists() else None,
        )

        warnings: list[str] = []
        try:
            vl_spec = resolve_model_data(
                vl_spec,
                spec,
                models_dir=models_dir,
                data_base_dir=project_dir,
            )
        except Exception as e:
            warnings.append(f"Data resolution skipped: {e}")

        await manager.broadcast(
            {
                "type": "compile_result",
                "path": rel,
                "vega_lite_spec": vl_spec,
                "errors": [],
                "warnings": warnings,
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
            }
        )
    except Exception as e:
        await manager.broadcast(
            {
                "type": "compile_result",
                "path": rel,
                "vega_lite_spec": None,
                "errors": [str(e)],
                "warnings": [],
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
) -> None:
    """Read a dashboard YAML file, compile it, and broadcast the result."""
    from shelves.studio.routes.dashboard import run_dashboard_pipeline

    try:
        content = abs_path.read_text()
        effective_project_dir = project_dir or abs_path.parent
        resolved_charts = charts_dir or (effective_project_dir / "charts")
        result = await run_dashboard_pipeline(
            content,
            effective_project_dir,
            resolved_charts,
            theme_path,
            models_dir=models_dir,
        )
        await manager.broadcast(
            {
                "type": "dashboard_compile_result",
                "path": rel,
                **result,
            }
        )
    except Exception as e:
        await manager.broadcast(
            {
                "type": "dashboard_compile_result",
                "path": rel,
                "html": None,
                "errors": [str(e)],
                "warnings": [],
                "component_tree": [],
            }
        )
