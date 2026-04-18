// ─── Main Entry Point ──────────────────────────────────────
// Initializes all modules and wires the compile router.

import { state, COMPILE_DEBOUNCE_MS, updateStatusBadge } from './state.js';
import { connectWebSocket } from './websocket.js';
import { initEditor, setCompileFunction, compileCurrentContent } from './editor.js';
import { initPreview } from './preview.js';
import { initSidebar } from './sidebar.js';
import {
  initDashboard, isDashboardYaml, compileDashboardContent,
  applyDashboardLayout, restoreChartLayout,
} from './dashboard.js';
import { initTerminal } from './terminal.js';

// ─── Initialize Modules ───────────────────────────────────
await initEditor();
initPreview();
initSidebar();
initDashboard();
await initTerminal();
connectWebSocket();

// ─── Compile Router ────────────────────────────────────────
// Routes to chart or dashboard pipeline based on YAML content.
function compileDashboardOrChart() {
  const content = state.editor.getValue();
  if (!content.trim()) {
    if (state.dashboardMode) restoreChartLayout();
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: {
        vega_lite_spec: null, errors: [], warnings: [],
        path: state.currentFile?.path ?? null,
      },
    }));
    updateStatusBadge([]);
    return;
  }
  if (isDashboardYaml(content)) {
    if (!state.dashboardMode) applyDashboardLayout();
    compileDashboardContent();
  } else {
    if (state.dashboardMode) restoreChartLayout();
    compileCurrentContent();
  }
}

// Inject the compile function into the editor module
setCompileFunction(compileDashboardOrChart);

// ─── View Toggle Buttons ──────────────────────────────────
document.querySelectorAll('.view-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.currentView = btn.dataset.view;
    document.dispatchEvent(new CustomEvent('shelves:view-change', {
      detail: { view: btn.dataset.view },
    }));
  });
});
