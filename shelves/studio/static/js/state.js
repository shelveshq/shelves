// ─── Shared State ──────────────────────────────────────────
export const state = {
  editor: null,        // Monaco editor instance
  currentFile: null,   // { path: string, dirty: boolean } | null
  tabs: [],            // [{ path, dirty }]
  compileTimer: null,
  currentView: 'chart', // 'chart' | 'json' | 'dashboard'
  lastCompileResult: null,
  vegaView: null,       // vega-embed View instance for cleanup
  dashboardMode: false,
};

// ─── Constants ─────────────────────────────────────────────
export const COMPILE_DEBOUNCE_MS = 300;
export const WS_RECONNECT_MS = 2000;
export const STORAGE_KEY_SETTINGS = 'shelves-studio-settings';
export const STORAGE_KEY_PANE_WIDTH = 'shelves-studio-pane-width';

// ─── Shared Utilities ──────────────────────────────────────
export function updateStatusBadge(errors, warnings) {
  const badge = document.getElementById('status-badge');
  if (errors.length > 0) {
    badge.textContent = `${errors.length} error${errors.length > 1 ? 's' : ''}`;
    badge.className = 'status-error';
    badge.title = errors.join('\n');
  } else if (warnings && warnings.length > 0) {
    badge.textContent = `${warnings.length} warning${warnings.length > 1 ? 's' : ''}`;
    badge.className = 'status-warning';
    badge.title = warnings.join('\n');
  } else {
    badge.textContent = 'Valid';
    badge.className = 'status-valid';
    badge.title = '';
  }
}
