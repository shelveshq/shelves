"""
Dashboard loading veil ends on rendered, not on compile-result (SHE-67).

A `dashboard_compile_result` only proves the HTML string exists — the iframe
still has to parse it, fetch Vega from the CDN, and render every sheet. The
veil must persist until the composed page posts {type:'shelves:rendered'}
(re-dispatched by dashboard.js as `shelves:dashboard-rendered`), while error
results — which paint the overlay synchronously — end it immediately. Reuses
the node event-flow harness (tests/support/run_broadcast_guard.mjs).
"""

from __future__ import annotations

from tests.test_studio_broadcast_guard import run_scenarios


def test_veil_arms_for_dashboard_compile():
    assert run_scenarios()["dashVeilArmed"] is True


def test_veil_survives_the_compile_result():
    assert run_scenarios()["dashVeilAfterResult"] is True


def test_veil_ends_on_rendered_signal():
    assert run_scenarios()["dashVeilAfterRendered"] is False


def test_veil_ends_immediately_on_error_result():
    assert run_scenarios()["dashVeilAfterError"] is False
