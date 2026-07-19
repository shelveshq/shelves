// Runs preview.js under node with a minimal DOM stub and a working
// document-event bus, then exercises the Data view (SHE-43): the resolved
// rows table rendered from vega_lite_spec.data.values — model-name header,
// escaping, numeric alignment, 500-row cap, and the skipped/empty/error
// degradation states.
//
// Usage: node run_data_view.mjs
// Prints one JSON object of observations (asserted by
// tests/test_studio_data_view.py).

const els = new Map();

function stubEl(id) {
  if (!els.has(id)) {
    els.set(id, {
      id,
      style: {},
      innerHTML: '',
      textContent: '',
      className: '',
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

globalThis.window = { addEventListener() {} };

globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  disconnect() {}
};

const dispatch = (type, detail) =>
  document.dispatchEvent(new CustomEvent(type, { detail }));

const { state } = await import('../../shelves/studio/static/js/state.js');
const { initPreview } = await import('../../shelves/studio/static/js/preview.js');

initPreview();

const out = {};
const dataView = stubEl('data-view');
const preview = stubEl('preview');
const errorOverlay = stubEl('error-overlay');

state.currentFile = { path: 'charts/a.yaml', dirty: false };
state.dashboardMode = false;

// ── S1: table renders — model header, escaping, numeric class, cell types ──
state.currentView = 'data';
dispatch('shelves:compile-result', {
  path: null, model: 'orders', errors: [], warnings: [],
  vega_lite_spec: { mark: 'bar', data: { values: [
    { country: 'US', revenue: 45000, flag: true, meta: { x: 1 }, note: null },
    { country: 'DE', revenue: 30500, flag: false, meta: { x: 2 }, note: 'a<b' },
  ] } },
});
out.tableShown = dataView.style.display === 'flex';
out.previewHidden = preview.style.display === 'none';
out.overlayShownDuringTable = errorOverlay.style.display === 'block';
out.tableHtml = dataView.innerHTML;

// ── S2: missing model key (stale broadcast from an old server) ──
dispatch('shelves:compile-result', {
  path: null, errors: [], warnings: [],
  vega_lite_spec: { mark: 'bar', data: { values: [{ a: 1 }] } },
});
out.noModelHtml = dataView.innerHTML;

// ── S3: 1200 rows — capped at 500 with a truncation footer ──
const bigValues = [];
for (let n = 0; n < 1200; n++) bigValues.push({ i: n, v: n * 2 });
dispatch('shelves:compile-result', {
  path: null, model: 'orders', errors: [], warnings: [],
  vega_lite_spec: { mark: 'bar', data: { values: bigValues } },
});
out.capHtml = dataView.innerHTML;

// ── S4: view toggle re-renders the last result without a new compile ──
// Chart view first: the stub never defines vegaEmbed, so renderChart paints
// the SHE-77 error card — the result must still be stored for the toggle.
state.currentView = 'chart';
dispatch('shelves:compile-result', {
  path: null, model: 'orders', errors: [], warnings: [],
  vega_lite_spec: { mark: 'bar', data: { values: [{ a: 1 }, { a: 2 }] } },
});
state.currentView = 'data';
dispatch('shelves:view-change', { view: 'data' });
out.rerenderShown = dataView.style.display === 'flex';
out.rerenderOverlayHidden = errorOverlay.style.display === 'none';
out.rerenderHtml = dataView.innerHTML;

// ── S5: data resolution skipped — warning text shown, no table ──
dispatch('shelves:compile-result', {
  path: null, model: 'orders', errors: [],
  warnings: ['Data resolution skipped: CUBE_API_URL not set'],
  vega_lite_spec: { mark: 'bar' },
});
out.skippedHtml = dataView.innerHTML;

// ── S6: no values, no warning (silent inline no-op) ──
dispatch('shelves:compile-result', {
  path: null, model: 'orders', errors: [], warnings: [],
  vega_lite_spec: { mark: 'bar' },
});
out.noValuesHtml = dataView.innerHTML;

// ── S7: zero rows ──
dispatch('shelves:compile-result', {
  path: null, model: 'orders', errors: [], warnings: [],
  vega_lite_spec: { mark: 'bar', data: { values: [] } },
});
out.zeroHtml = dataView.innerHTML;

// ── S8: ragged rows — union columns, missing cells render as null ──
dispatch('shelves:compile-result', {
  path: null, model: 'orders', errors: [], warnings: [],
  vega_lite_spec: { mark: 'bar', data: { values: [{ a: 1 }, { a: 2, b: 'x' }] } },
});
out.raggedHtml = dataView.innerHTML;

// ── S8b: malformed values — never a TypeError, never a stale table ──
// bind_data inlines whatever the source JSON contains; a non-array top level
// or null rows must degrade to a message / null cells (PR #67 review).
dispatch('shelves:compile-result', {
  path: null, model: 'orders', errors: [], warnings: [],
  vega_lite_spec: { mark: 'bar', data: { values: { a: 1 } } },
});
out.nonArrayHtml = dataView.innerHTML;

dispatch('shelves:compile-result', {
  path: null, model: 'orders', errors: [], warnings: [],
  vega_lite_spec: { mark: 'bar', data: { values: null } },
});
out.nullValuesHtml = dataView.innerHTML;

dispatch('shelves:compile-result', {
  path: null, model: 'orders', errors: [], warnings: [],
  vega_lite_spec: { mark: 'bar', data: { values: [null, { a: 1 }] } },
});
out.nullRowHtml = dataView.innerHTML;

// ── S9: compile error while in Data view — overlay, table hidden ──
dispatch('shelves:compile-result', {
  path: null, model: null, warnings: [],
  vega_lite_spec: null,
  errors: [{ friendly_msg: 'Required field', msg: 'missing', source: 'dsl' }],
});
out.errorOverlayShown = errorOverlay.style.display === 'block';
out.dataViewHiddenOnError = dataView.style.display === 'none';

// ── S10: null spec, no errors — empty state, no throw ──
dispatch('shelves:compile-result', {
  path: null, model: null, errors: [], warnings: [], vega_lite_spec: null,
});
out.dataViewHiddenOnEmpty = dataView.style.display === 'none';

console.log(JSON.stringify(out));
process.exit(0);
