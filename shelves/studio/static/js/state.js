// ─── Shared State ──────────────────────────────────────────
export const state = {
  editor: null,        // Monaco editor instance
  currentFile: null,   // { path: string, dirty: boolean } | null
  compileTimer: null,
  currentView: 'chart', // 'chart' | 'data' | 'dashboard'
  lastCompileResult: null,
  vegaView: null,       // vega-embed View instance for cleanup
  dashboardMode: false,
  lastCompileTimeMs: null,
  compiling: false,
  markerErrors: 0,
  markerWarnings: 0,
  // Dashboard compile diagnostics have no Monaco markers (plain strings, no
  // line mapping), so they feed the status bar through their own counters.
  dashboardErrors: 0,
  dashboardWarnings: 0,
  // Broadcast-WS connection: 'connected' | 'reconnecting' | 'unreachable'.
  // While not connected, live reload and watcher broadcasts are dead even
  // though local editing still works (SHE-66).
  wsStatus: 'connected',
  // Save lifecycle (SHE-65): 'failed' persists until the next save attempt
  // or until the user resumes typing; 'saved' is a transient flash.
  saveStatus: null,     // null | 'saving' | 'saved' | 'failed'
  saveError: null,      // string when failed
  // The open file was deleted on disk (SHE-51). The buffer is never
  // auto-closed — it may be the only surviving copy; saving recreates it.
  fileDeleted: false,
  // File navigation history (SHE-40). stack holds opened paths oldest→newest;
  // index points at the entry for the file currently open. Navigation moves
  // index without pushing; a fresh open truncates everything after index.
  nav: { stack: [], index: -1 },
};

// True when a compile/dashboard result belongs to the open buffer. Local
// compiles stamp the current file's path (or null when nothing is open);
// watcher broadcasts stamp the changed file's path — a result for a foreign
// path must not repaint this client's preview, markers, or status.
export function resultIsForCurrentFile(detail) {
  const path = detail?.path ?? null;
  return path === null || path === (state.currentFile?.path ?? null);
}

// ─── Constants ─────────────────────────────────────────────
export const COMPILE_DEBOUNCE_MS = 300;
export const WS_RECONNECT_MS = 2000;
export const WS_DOWN_GATE_MS = 1000;    // don't flash "Reconnecting…" on a blip
export const WS_UNREACHABLE_AFTER = 5;  // failed retries before escalating
export const STORAGE_KEY_SETTINGS = 'shelves-studio-settings';
export const STORAGE_KEY_PANE_WIDTH = 'shelves-studio-pane-width';
export const NAV_STACK_MAX = 100;   // history entries kept (oldest dropped)

// ─── Status Bar ───────────────────────────────────────────
export function updateStatusBar() {
  const dot = document.querySelector('#statusbar .sh-status-dot');
  const msg = document.querySelector('#statusbar .sh-status-msg');
  if (!dot || !msg) return;

  // Connection state outranks everything: with the server down, live reload
  // is dead and any in-flight compile will fail anyway (SHE-66).
  if (state.wsStatus === 'reconnecting') {
    dot.className = 'sh-status-dot reconnecting';
    msg.textContent = 'Reconnecting…';
    return;
  }
  if (state.wsStatus === 'unreachable') {
    dot.className = 'sh-status-dot reconnecting';
    msg.textContent = 'Server unreachable — is shelves-studio still running?';
    return;
  }

  if (state.compiling) {
    dot.className = 'sh-status-dot compiling';
    msg.textContent = 'Compiling…';
    return;
  }

  // Save lifecycle (SHE-65) sits between compiling and the marker counts.
  if (state.saveStatus === 'saving') {
    dot.className = 'sh-status-dot compiling';
    msg.textContent = 'Saving…';
    return;
  }
  if (state.saveStatus === 'failed') {
    dot.className = 'sh-status-dot error';
    msg.textContent = `Save failed: ${state.saveError ?? 'unknown error'}`;
    return;
  }
  if (state.saveStatus === 'saved') {
    dot.className = 'sh-status-dot';
    msg.textContent = 'Saved';
    return;
  }

  // Deletion outranks compile chatter but not an in-flight compile (SHE-51).
  if (state.fileDeleted && state.currentFile) {
    dot.className = 'sh-status-dot warn';
    msg.textContent = `${state.currentFile.path} deleted on disk — saving will recreate it`;
    return;
  }

  const ec = (state.dashboardMode ? state.dashboardErrors : state.markerErrors) ?? 0;
  const wc = (state.dashboardMode ? state.dashboardWarnings : state.markerWarnings) ?? 0;

  if (ec > 0 && wc > 0) {
    dot.className = 'sh-status-dot error';
    msg.textContent =
      `${ec} error${ec !== 1 ? 's' : ''}, ${wc} warning${wc !== 1 ? 's' : ''}`;
  } else if (ec > 0) {
    dot.className = 'sh-status-dot error';
    msg.textContent = `${ec} error${ec !== 1 ? 's' : ''}`;
  } else if (wc > 0) {
    dot.className = 'sh-status-dot warn';
    msg.textContent = `${wc} warning${wc !== 1 ? 's' : ''}`;
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
  if (state.fileDeleted) {
    html += '<span class="sh-crumb-deleted">deleted</span>';
  }
  crumb.innerHTML = html;
}
