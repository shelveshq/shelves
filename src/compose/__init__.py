"""
Compose — End-to-end dashboard composition

Orchestrates: dashboard YAML → chart compilation → layout translation → HTML.
"""

from src.compose.dashboard import compose_dashboard

__all__ = ["compose_dashboard"]
