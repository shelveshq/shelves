// ─── Main Entry Point ──────────────────────────────────────
// Initializes all modules and wires the compile router.

import { state, COMPILE_DEBOUNCE_MS, updateStatusBar } from './state.js';
import { connectWebSocket } from './websocket.js';
import { initEditor, setCompileFunction, compileCurrentContent } from './editor.js';
import { initPreview } from './preview.js';
import { initSidebar } from './sidebar.js';
import {
  initDashboard, isDashboardYaml, compileDashboardContent,
  applyDashboardLayout, restoreChartLayout,
} from './dashboard.js';
import { initTerminal, toggleTerminalPanel } from './terminal.js';

// ─── Initialize Modules ───────────────────────────────────
await initEditor();
initPreview();
initSidebar();
initDashboard();
await initTerminal();
connectWebSocket();

// ─── Compile Router ────────────────────────────────────────
function compileDashboardOrChart() {
  const content = state.editor.getValue();
  if (!content.trim()) {
    state.compiling = false;
    if (state.dashboardMode) restoreChartLayout();
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: {
        vega_lite_spec: null, errors: [], warnings: [],
        path: state.currentFile?.path ?? null,
      },
    }));
    updateStatusBar([]);
    return;
  }
  state.compiling = true;
  updateStatusBar();
  if (isDashboardYaml(content)) {
    if (!state.dashboardMode) applyDashboardLayout();
    compileDashboardContent();
  } else {
    if (state.dashboardMode) restoreChartLayout();
    compileCurrentContent();
  }
}

setCompileFunction(compileDashboardOrChart);

// ─── Status Bar Terminal Toggle ───────────────────────────
const termBtn = document.querySelector('#statusbar .sh-status-term');
if (termBtn) {
  termBtn.addEventListener('click', toggleTerminalPanel);
}

// ─── Cmd+K Placeholder ───────────────────────────────────
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
  }
});
