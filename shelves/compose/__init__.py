"""
Compose — End-to-end dashboard composition

Orchestrates: dashboard YAML → chart compilation → layout translation → HTML.
"""

from shelves.compose.dashboard import compose_dashboard

__all__ = ["compose_dashboard"]
