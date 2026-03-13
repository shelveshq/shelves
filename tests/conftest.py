"""
Shared test fixtures and helpers.
"""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
YAML_DIR = FIXTURES_DIR / "yaml"
DATA_DIR = FIXTURES_DIR / "data"


def load_yaml(name: str) -> str:
    """Load a YAML fixture file by name."""
    return (YAML_DIR / name).read_text()


def load_data(name: str) -> str:
    """Load a JSON data fixture by name."""
    return (DATA_DIR / name).read_text()
