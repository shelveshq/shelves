"""
Dashboard compile errors must reach the status bar (SHE-50).

`updateStatusBar()` renders from state only; dashboard results have no Monaco
markers, so `dashboard.js` feeds `state.dashboardErrors/-Warnings` from each
result and the status bar reads those counters in dashboard mode. Reuses the
node event-flow harness from the broadcast-guard tests
(tests/support/run_broadcast_guard.mjs).
"""

from __future__ import annotations

from tests.test_studio_broadcast_guard import run_scenarios


def test_dashboard_error_turns_status_dot_red():
    out = run_scenarios()
    assert out["dashboardErrorDot"] == "sh-status-dot error"
    assert out["dashboardErrorMsg"] == "1 error, 1 warning"


def test_dashboard_success_returns_dot_to_green():
    assert run_scenarios()["dashboardOkDot"] == "sh-status-dot"


def test_leaving_dashboard_mode_resets_counters():
    assert run_scenarios()["dashboardCountersReset"] is True
