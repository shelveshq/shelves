// ─── Main Entry Point ──────────────────────────────────────
// Initializes all modules and wires the compile router.

import { state, COMPILE_DEBOUNCE_MS, updateStatusBar } from './state.js';
import { connectWebSocket } from './websocket.js';
import { initEditor, setCompileFunction, compileCurrentContent } from './editor.js';
import { initPreview } from './preview.js';
import { initSidebar, toggleSidebar } from './sidebar.js';
import {
  initDashboard, isDashboardYaml, compileDashboardContent,
  applyDashboardLayout, restoreChartLayout,
} from './dashboard.js';
import { initTerminal, toggleTerminalPanel } from './terminal.js';

// ─── Initialize Modules ───────────────────────────────────
// Boot is PARALLEL (SHE-64): the file tree, preview, and live reload must
// neither wait on Monaco's multi-second CDN load nor die with it — a rejected
// top-level await here used to abort the whole module and leave the entire UI
// blank. initEditor guards its own failure (error card in the editor pane);
// the terminal is best-effort.
initPreview();
initSidebar();
initDashboard();
connectWebSocket();
initEditor();
initTerminal().catch((e) => console.error('[shelves] terminal init failed:', e));

// ─── Compile Router ────────────────────────────────────────
function classifyContent(content) {
  if (isDashboardYaml(content)) return 'dashboard';
  // Chart YAML must have a top-level `sheet:` key — same signal the backend
  // uses (routes/compile.py checks `"sheet" in raw`). Line-anchored, first
  // 40 lines, mirrors isDashboardYaml's cheap heuristic. The backend remains
  // the authority; this only decides which surface to show.
  const head = content.split('\n').slice(0, 40);
  if (head.some(l => /^sheet\s*:/.test(l))) return 'chart';
  return 'other';
}

// Tell listeners (editor.js schema routing, SHE-48) what kind of buffer the
// router just classified. Every compile pass announces; listeners dedupe.
function announceBufferKind(kind) {   // 'chart' | 'dashboard' | 'other' | 'empty'
  document.dispatchEvent(new CustomEvent('shelves:buffer-kind', { detail: { kind } }));
}

function compileDashboardOrChart() {
  const content = state.editor.getValue();
  if (!content.trim()) {
    announceBufferKind('empty');
    state.compiling = false;
    if (state.dashboardMode) restoreChartLayout();
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: {
        vega_lite_spec: null, errors: [], warnings: [],
        path: state.currentFile?.path ?? null,
      },
    }));
    updateStatusBar();
    return;
  }

  const kind = classifyContent(content);
  announceBufferKind(kind);
  if (kind === 'other') {
    // Skip the POST entirely — the backend would just return {spec:null,errors:[]}
    state.compiling = false;
    if (state.dashboardMode) restoreChartLayout();
    document.dispatchEvent(new CustomEvent('shelves:non-chart-file', {
      detail: { path: state.currentFile?.path ?? null },
    }));
    updateStatusBar();
    return;
  }

  state.compiling = true;
  updateStatusBar();
  // Arm the loading veil (preview.js). Every start pairs with exactly one of
  // compile-result / dashboard-result / non-chart-file — the compile fns'
  // success AND failure paths all dispatch one.
  document.dispatchEvent(new CustomEvent('shelves:compile-start'));
  if (kind === 'dashboard') {
    if (!state.dashboardMode) applyDashboardLayout();
    compileDashboardContent();
  } else {
    if (state.dashboardMode) restoreChartLayout();
    compileCurrentContent();
  }
}

setCompileFunction(compileDashboardOrChart);

// After a reconnect the preview may be stale (the server restarted; watcher
// results were lost while down) — recompile the open buffer (SHE-66).
document.addEventListener('shelves:ws-reconnected', () => {
  if (state.currentFile) compileDashboardOrChart();
});

// ─── Status Bar Terminal Toggle ───────────────────────────
// By id, not `.sh-status-term` — the Files chip shares that class (SHE-41).
const termBtn = document.getElementById('terminal-toggle-status');
if (termBtn) {
  termBtn.addEventListener('click', toggleTerminalPanel);
}

// ─── Sidebar Toggle Shortcut (SHE-41) ─────────────────────
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b' && !e.shiftKey && !e.altKey) {
    e.preventDefault();
    toggleSidebar();
  }
});

// ─── Cmd+K Placeholder ───────────────────────────────────
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
  }
});
