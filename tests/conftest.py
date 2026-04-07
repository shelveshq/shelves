"""
Shared test fixtures and helpers.
"""

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


def compile_fixture(name: str, models_dir: Path | None = None) -> dict:
    """Parse a YAML fixture and compile to Vega-Lite dict.

    Args:
        name: YAML fixture filename (e.g. "simple_bar.yaml")
        models_dir: Path to models directory. Defaults to MODELS_DIR
                    (tests/fixtures/models/).
    """
    spec = parse_chart(load_yaml(name))
    return translate_chart(spec, models_dir=models_dir or MODELS_DIR)
