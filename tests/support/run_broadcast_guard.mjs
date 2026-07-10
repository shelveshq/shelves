// Runs preview.js + dashboard.js under node with a minimal DOM stub and a
// working document-event bus, then replays the watcher-broadcast scenarios
// from SHE-49: results stamped with a foreign path must not repaint the
// preview, the JSON view, the dashboard iframe, or end the loading veil.
//
// Usage: node run_broadcast_guard.mjs
// Prints one JSON object of observations (asserted by
// tests/test_studio_broadcast_guard.py).

const els = new Map();

function stubEl(id) {
  if (!els.has(id)) {
    els.set(id, {
      id,
      style: {},
      innerHTML: '',
      textContent: '',
      className: '',
      srcdoc: null,
      classList: {
        _set: new Set(),
        add(c) { this._set.add(c); },
        remove(c) { this._set.delete(c); },
        toggle(c, force) { force ? this._set.add(c) : this._set.delete(c); },
        contains(c) { return this._set.has(c); },
      },
      addEventListener() {},
      appendChild() {},
      removeChild() {},
      getBoundingClientRect() { return { width: 0, height: 0, left: 0, top: 0 }; },
      querySelector(sel) { return stubEl(`${id}::${sel}`); },
      querySelectorAll() { return []; },
    });
  }
  return els.get(id);
}

const listeners = new Map();

globalThis.document = {
  getElementById: stubEl,
  querySelector: (sel) => stubEl(`doc::${sel}`),
  querySelectorAll: () => [],
  createElement: (tag) => stubEl(`created-${tag}-${els.size}`),
  addEventListener(type, fn) {
    if (!listeners.has(type)) listeners.set(type, []);
    listeners.get(type).push(fn);
  },
  dispatchEvent(ev) {
    for (const fn of listeners.get(ev.type) ?? []) fn(ev);
  },
};

globalThis.CustomEvent = class CustomEvent {
  constructor(type, opts) {
    this.type = type;
    this.detail = opts?.detail;
  }
};

globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  disconnect() {}
};

const dispatch = (type, detail) =>
  document.dispatchEvent(new CustomEvent(type, { detail }));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const { state } = await import('../../shelves/studio/static/js/state.js');
const { initPreview } = await import('../../shelves/studio/static/js/preview.js');
const { initDashboard } = await import('../../shelves/studio/static/js/dashboard.js');

initPreview();
initDashboard();

const out = {};
const previewPane = stubEl('preview-pane');
const jsonView = stubEl('json-view');
const iframe = stubEl('dashboard-iframe');

// ── Chart scenarios: charts/a.yaml open, JSON view (no vegaEmbed needed) ──
state.currentFile = { path: 'charts/a.yaml', dirty: false };
state.currentView = 'json';
state.dashboardMode = false;
state.lastCompileResult = null;

dispatch('shelves:compile-start');
await sleep(200);  // past LOADING_DELAY_MS
out.veilArmed = previewPane.classList.contains('is-compiling');

// Foreign watcher broadcast: must not repaint and must not end the veil.
dispatch('shelves:compile-result', {
  path: 'charts/b.yaml', vega_lite_spec: { mark: 'bar' }, errors: [], warnings: [],
});
out.foreignChartApplied = state.lastCompileResult !== null;
out.foreignJsonPainted = jsonView.innerHTML !== '';
out.veilAfterForeign = previewPane.classList.contains('is-compiling');

// Broadcast for the OPEN file: applies and ends the veil.
dispatch('shelves:compile-result', {
  path: 'charts/a.yaml', vega_lite_spec: { mark: 'line' }, errors: [], warnings: [],
});
out.ownChartApplied = state.lastCompileResult?.vega_lite_spec?.mark === 'line';
out.veilAfterOwn = previewPane.classList.contains('is-compiling');

// Local result (no path stamp): applies.
dispatch('shelves:compile-result', {
  path: null, vega_lite_spec: { mark: 'area' }, errors: [], warnings: [],
});
out.localChartApplied = state.lastCompileResult?.vega_lite_spec?.mark === 'area';

// ── Dashboard scenarios ──
// Foreign dashboard broadcast while a chart is open: iframe must stay empty.
state.currentView = 'chart';
dispatch('shelves:dashboard-result', {
  path: 'dashboards/x.yaml', html: '<html>x</html>',
  errors: [], warnings: [], component_tree: [],
});
out.foreignDashboardPainted = iframe.srcdoc !== null;

// Broadcast for the open dashboard file with the dashboard surface active.
state.currentFile = { path: 'dashboards/x.yaml', dirty: false };
state.dashboardMode = true;
dispatch('shelves:dashboard-result', {
  path: 'dashboards/x.yaml', html: '<html>x</html>',
  errors: [], warnings: [], component_tree: [],
});
out.ownDashboardPainted = iframe.srcdoc === '<html>x</html>';

// Local dashboard compile (no path stamp): applies.
iframe.srcdoc = null;
dispatch('shelves:dashboard-result', {
  html: '<html>local</html>', errors: [], warnings: [], component_tree: [],
});
out.localDashboardPainted = iframe.srcdoc === '<html>local</html>';

// ── SHE-50: dashboard compile errors reach the status bar ──
// Still in dashboard mode with dashboards/x.yaml open.
const statusDot = stubEl('doc::#statusbar .sh-status-dot');
const statusMsg = stubEl('doc::#statusbar .sh-status-msg');

dispatch('shelves:dashboard-result', {
  html: null, errors: ['boom'], warnings: ['careful'], component_tree: [],
});
out.dashboardErrorDot = statusDot.className;
out.dashboardErrorMsg = statusMsg.textContent;

dispatch('shelves:dashboard-result', {
  html: '<html>ok</html>', errors: [], warnings: [], component_tree: [],
});
out.dashboardOkDot = statusDot.className;

// Chart mode must stay marker-driven: leaving dashboard mode resets the
// dashboard counters so they can't bleed into chart status.
const { restoreChartLayout } = await import('../../shelves/studio/static/js/dashboard.js');
state.dashboardErrors = 3;
restoreChartLayout();
out.dashboardCountersReset = state.dashboardErrors === 0 && state.dashboardWarnings === 0;

console.log(JSON.stringify(out));
