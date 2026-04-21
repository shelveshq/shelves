// ─── Shared State ──────────────────────────────────────────
export const state = {
  editor: null,        // Monaco editor instance
  currentFile: null,   // { path: string, dirty: boolean } | null
  compileTimer: null,
  currentView: 'chart', // 'chart' | 'json' | 'dashboard'
  lastCompileResult: null,
  vegaView: null,       // vega-embed View instance for cleanup
  dashboardMode: false,
  lastCompileTimeMs: null,
  compiling: false,
};

// ─── Constants ─────────────────────────────────────────────
export const COMPILE_DEBOUNCE_MS = 300;
export const WS_RECONNECT_MS = 2000;
export const STORAGE_KEY_SETTINGS = 'shelves-studio-settings';
export const STORAGE_KEY_PANE_WIDTH = 'shelves-studio-pane-width';

// ─── Status Bar ───────────────────────────────────────────
export function updateStatusBar(errors, warnings) {
  const dot = document.querySelector('#statusbar .sh-status-dot');
  const msg = document.querySelector('#statusbar .sh-status-msg');
  if (!dot || !msg) return;

  if (state.compiling) {
    dot.className = 'sh-status-dot compiling';
    msg.textContent = 'Compiling…';
    return;
  }

  if (errors && errors.length > 0) {
    dot.className = 'sh-status-dot error';
    msg.textContent = `${errors.length} error${errors.length > 1 ? 's' : ''}`;
  } else if (warnings && warnings.length > 0) {
    dot.className = 'sh-status-dot warn';
    msg.textContent = `${warnings.length} warning${warnings.length > 1 ? 's' : ''}`;
  } else {
    dot.className = 'sh-status-dot';
    const timeStr = state.lastCompileTimeMs != null
      ? `Compiled in ${state.lastCompileTimeMs}ms`
      : 'Ready';
    msg.textContent = state.currentFile ? timeStr : 'No file open';
  }
}

// ─── Breadcrumb ───────────────────────────────────────────
export function updateBreadcrumb(path, dirty) {
  const crumb = document.querySelector('#header .sh-crumb');
  if (!crumb) return;

  if (!path) {
    crumb.innerHTML = '<span class="sh-crumb-none">no file open</span>';
    return;
  }

  const parts = path.split('/');
  const fileName = parts.pop();
  const dirParts = parts;

  let html = '';
  for (const dir of dirParts) {
    html += `<span>${dir}</span><span class="sh-crumb-sep" style="margin:0 4px">/</span>`;
  }
  html += `<span class="sh-crumb-file">${fileName}</span>`;
  if (dirty) {
    html += '<span class="sh-dirty">•</span>';
  }
  crumb.innerHTML = html;
}
