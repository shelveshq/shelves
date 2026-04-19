"""
Shared test fixtures and helpers.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart

FIXTURES_DIR = Path(__file__).parent / "fixtures"
YAML_DIR = FIXTURES_DIR / "yaml"
DATA_DIR = FIXTURES_DIR / "data"
MODELS_DIR = FIXTURES_DIR / "models"
LAYOUT_DIR = FIXTURES_DIR / "layout"


def load_yaml(name: str) -> str:
    """Load a YAML fixture file by name."""
    return (YAML_DIR / name).read_text()


def load_layout_yaml(name: str) -> str:
    """Load a layout YAML fixture file by name."""
    return (LAYOUT_DIR / name).read_text()


def load_data(name: str) -> str:
    """Load a JSON data fixture by name."""
    return (DATA_DIR / name).read_text()


class SubprocessOutputDrainer:
    """
    Drain a subprocess's stdout/stderr pipes into buffers in background threads.

    Leaving PIPE pipes undrained can deadlock long-running subprocesses when
    the kernel pipe buffer fills up. Using DEVNULL would fix the hang but
    swallow diagnostics — so we keep the pipes and stream them into memory
    where a test assertion can include them in its failure message.

    Usage:
        proc = subprocess.Popen(..., stdout=PIPE, stderr=PIPE)
        drainer = SubprocessOutputDrainer(proc)
        try:
            ...
        finally:
            proc.wait(timeout=...)
            drainer.join()
            # drainer.stdout_text / drainer.stderr_text now hold output
    """

    def __init__(self, proc: subprocess.Popen) -> None:
        self._stdout_buf = bytearray()
        self._stderr_buf = bytearray()
        self._t_out = threading.Thread(
            target=self._drain, args=(proc.stdout, self._stdout_buf), daemon=True
        )
        self._t_err = threading.Thread(
            target=self._drain, args=(proc.stderr, self._stderr_buf), daemon=True
        )
        self._t_out.start()
        self._t_err.start()

    @staticmethod
    def _drain(pipe, sink: bytearray) -> None:
        if pipe is None:
            return
        try:
            for chunk in iter(lambda: pipe.read(4096), b""):
                sink.extend(chunk)
        except (OSError, ValueError):
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def join(self, timeout: float = 5.0) -> None:
        self._t_out.join(timeout=timeout)
        self._t_err.join(timeout=timeout)

    @property
    def stdout_text(self) -> str:
        return self._stdout_buf.decode(errors="replace")

    @property
    def stderr_text(self) -> str:
        return self._stderr_buf.decode(errors="replace")


def compile_fixture(name: str, models_dir: Path | None = None) -> dict:
    """Parse a YAML fixture and compile to Vega-Lite dict.

    Args:
        name: YAML fixture filename (e.g. "simple_bar.yaml")
        models_dir: Path to models directory. Defaults to MODELS_DIR
                    (tests/fixtures/models/).
    """
    spec = parse_chart(load_yaml(name))
    return translate_chart(spec, models_dir=models_dir or MODELS_DIR)
