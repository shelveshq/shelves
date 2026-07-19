// ─── Preview Module ────────────────────────────────────────
// Chart rendering, Data view (resolved rows table), error overlay,
// preview header.

import { state, resultIsForCurrentFile } from './state.js';

const elPreview        = document.getElementById('preview');
const elChartContainer = document.getElementById('chart-container');
const elDataView       = document.getElementById('data-view');
const elErrorOverlay   = document.getElementById('error-overlay');

// Mirror of shelves/translator/layout.py::_is_compound_spec. Compound specs
// (facet/concat/repeat) ignore width/height:"container", so we render them at
// natural size and let the card scroll instead of clipping them (KAN-298).
const COMPOUND_KEYS = ['facet', 'hconcat', 'vconcat', 'concat', 'repeat'];
function isCompoundSpec(spec) {
  return COMPOUND_KEYS.some(k => k in spec);
}

// ─── Loading Veil ─────────────────────────────────────────
// Compiles never blank the preview: the stale render stays visible and gets
// a dim veil + "Compiling…" pill, and only if the compile is actually slow.
// The gate is patience-after-starting; don't tie it to COMPILE_DEBOUNCE_MS
// (quiet-time-before-starting) — they measure different things.
const LOADING_DELAY_MS = 150;   // don't flash a loading state for fast compiles
let loadingTimer = null;

function beginLoadingState() {
  clearTimeout(loadingTimer);
  loadingTimer = setTimeout(() => {
    document.getElementById('preview-pane').classList.add('is-compiling');
  }, LOADING_DELAY_MS);
}

function endLoadingState() {
  clearTimeout(loadingTimer);
  loadingTimer = null;
  document.getElementById('preview-pane').classList.remove('is-compiling');
}

// ─── Preview Header ───────────────────────────────────────
export function renderPreviewHeader(mode) {
  const header = document.getElementById('preview-header');
  if (!header) return;

  const rightEl = header.querySelector('.sh-preview-right');
  const ambientEl = header.querySelector('.sh-preview-ambient');

  if (mode === 'dashboard') {
    if (ambientEl) ambientEl.textContent = '';
    rightEl.innerHTML = `
      <div id="view-toggles" class="sh-seg sh-seg-dark">
        <button class="sh-seg-btn is-active" data-zoom="fit">Fit</button>
        <button class="sh-seg-btn" data-zoom="100">100%</button>
        <button class="sh-seg-btn" data-zoom="50">50%</button>
      </div>`;
    rightEl.querySelectorAll('.sh-seg-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        rightEl.querySelectorAll('.sh-seg-btn').forEach(b => b.classList.remove('is-active'));
        btn.classList.add('is-active');
        document.dispatchEvent(new CustomEvent('shelves:dashboard-zoom', {
          detail: { zoom: btn.dataset.zoom },
        }));
      });
    });
  } else {
    const timeStr = state.lastCompileTimeMs != null
      ? `compiled in ${state.lastCompileTimeMs}ms`
      : '';
    if (ambientEl) ambientEl.textContent = timeStr;

    rightEl.innerHTML = `
      <div id="view-toggles" class="sh-seg">
        <button class="sh-seg-btn${state.currentView === 'chart' ? ' is-active' : ''}" data-view="chart">Chart</button>
        <button class="sh-seg-btn${state.currentView === 'data' ? ' is-active' : ''}" data-view="data">Data</button>
      </div>`;
    rightEl.querySelectorAll('.sh-seg-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        rightEl.querySelectorAll('.sh-seg-btn').forEach(b => b.classList.remove('is-active'));
        btn.classList.add('is-active');
        state.currentView = btn.dataset.view;
        document.dispatchEvent(new CustomEvent('shelves:view-change', {
          detail: { view: btn.dataset.view },
        }));
      });
    });
  }
}

function updateAmbientTime() {
  const ambientEl = document.querySelector('#preview-header .sh-preview-ambient');
  if (ambientEl && !state.dashboardMode && state.lastCompileTimeMs != null) {
    ambientEl.textContent = `compiled in ${state.lastCompileTimeMs}ms`;
  }
}

// ─── Error Overlay ─────────────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                  .replace(/"/g, '&quot;');
}

export function showErrorOverlay(errors, title = "Can't compile this chart") {
  elPreview.style.display = 'none';
  elDataView.style.display = 'none';
  elErrorOverlay.style.display = 'block';

  // Callers hide every other pane before invoking, so an empty error list
  // must still render feedback — a no-op here means a fully blank preview.
  const list = errors?.length
    ? errors
    : ['The compile failed without reporting an error. Check the terminal for details.'];

  const items = list.map(e => {
    if (typeof e === 'object' && (e.friendly_msg || e.msg)) {
      const badge = e.source === 'yaml' ? 'YAML' : e.source === 'dsl' ? 'DSL' : '';
      const loc   = e.display_loc?.length ? e.display_loc.join('.') : '';
      const line  = e.line ? `line ${e.line}` : '';
      const meta  = [badge, loc, line].filter(Boolean).join(' · ');
      const body  = esc(e.friendly_msg ?? e.msg);
      return `<li class="error-item">${meta ? `<span class="error-meta">${esc(meta)}</span> — ` : ''}${body}</li>`;
    }
    return `<li class="error-item">${esc(e)}</li>`;
  }).join('');

  elErrorOverlay.innerHTML = `
    <div class="error-card">
      <div class="error-title">${esc(title)}</div>
      <ul class="error-list">${items}</ul>
    </div>`;
}

export function hideErrorOverlay() {
  elErrorOverlay.style.display = 'none';
}

// ─── Empty State ──────────────────────────────────────────
export function showEmptyState({ title, sub }) {
  hideErrorOverlay();
  elDataView.style.display = 'none';
  elPreview.style.display = '';
  const card = document.getElementById('chart-card');
  card.classList.remove('is-scroll');
  elChartContainer.innerHTML = `
    <div class="sh-empty">
      <div class="sh-empty-inner">
        <div class="sh-empty-h">${esc(title)}</div>
        <div class="sh-empty-sub">${esc(sub)}</div>
      </div>
    </div>`;
  if (state.vegaView) { try { state.vegaView.finalize(); } catch (_) {} state.vegaView = null; }
}

// ─── Chart Rendering ───────────────────────────────────────
async function renderChart(result) {
  elDataView.style.display = 'none';

  if (!result || result.vega_lite_spec === null) {
    // A local compile of non-chart content still yields null-spec/no-error.
    if (result?.errors?.length) { showErrorOverlay(result.errors); }
    else { showEmptyState({ title: 'Nothing to render yet', sub: 'The compile returned no chart and no errors.' }); }
    return;
  }

  hideErrorOverlay();
  elPreview.style.display = '';

  const spec = result.vega_lite_spec;
  const compound = isCompoundSpec(spec);
  const card = document.getElementById('chart-card');

  // Compound specs render at natural size and SCROLL; single-view/layered
  // specs fit the container as before. Toggle scroll mode on the card so the
  // CSS switches between clip-and-fit and scroll-at-natural-size (KAN-298).
  card.classList.toggle('is-scroll', compound);

  // Single-view specs: fit the container (no scrollbars when they fit).
  // Compound specs: leave width/height untouched so Vega-Lite renders the
  // panels at their natural size (container sizing is ignored anyway).
  const embedSpec = compound
    ? spec
    : Object.assign({}, spec, {
        width: 'container',
        height: 'container',
        autosize: { type: 'fit', contains: 'padding' },
      });

  // The renderer globals load as classic <script> tags; if any of them failed
  // (network, ad-blocker), calling vegaEmbed throws a bare TypeError with no
  // hint of the cause. Name the problem instead (SHE-77).
  if (typeof window.vegaEmbed !== 'function') {
    showErrorOverlay(
      ['The vega render scripts did not load. Check your connection or '
       + 'ad-blocker, then reload the page.'],
      'Chart renderer failed to load',
    );
    return;
  }

  const buf = document.createElement('div');
  buf.style.cssText = 'position:absolute;inset:0;visibility:hidden;';
  elChartContainer.appendChild(buf);

  try {
    const { view } = await window.vegaEmbed(buf, embedSpec, {
      actions: false,
      renderer: 'canvas',
      patch: window.labelPatch,
    });
    if (state.vegaView) {
      try { state.vegaView.finalize(); } catch (_) {}
    }
    while (elChartContainer.firstChild !== buf) {
      elChartContainer.removeChild(elChartContainer.firstChild);
    }
    // Compound: let the embed take its natural size (CSS handles it). Single:
    // fill the container as before.
    buf.style.cssText = compound ? '' : 'width:100%;height:100%;';
    state.vegaView = view;
  } catch (e) {
    buf.remove();
    showErrorOverlay([String(e)], "Can't render this chart");
  }
}

// ─── Data View (SHE-43) ───────────────────────────────────
// The resolved rows behind the current chart, straight from
// vega_lite_spec.data.values (every backend inlines rows via bind_data).
// Granularity follows the binding: raw pre-aggregation rows for inline/file
// sources (Vega-Lite aggregates client-side), aggregated rows for Cube.
const DATA_ROW_CAP = 500;   // rows rendered; footer states the truncation

const fmtCount = (n) => n.toLocaleString('en-US');

function renderCell(v) {
  if (v == null) return '<span class="sh-data-null">null</span>';
  if (typeof v === 'object') return esc(JSON.stringify(v));
  return esc(String(v));
}

function dataHead(model, countText) {
  return `
    <div class="sh-data-head">
      <span class="sh-data-label">Data</span>
      <span class="sh-data-model">${esc(model ?? '—')}</span>
      <span class="sh-data-count">${esc(countText)}</span>
    </div>`;
}

function dataMessage(model, countText, message) {
  return dataHead(model, countText)
    + `<div class="sh-data-empty">${esc(message)}</div>`;
}

function buildDataTable(model, values) {
  const shown = values.slice(0, DATA_ROW_CAP);

  // Union of keys across displayed rows, first-seen order — inline data may
  // be ragged; adapter-backed rows are uniform and take the fast path.
  const columns = [];
  const seen = new Set();
  for (const row of shown) {
    for (const key of Object.keys(row)) {
      if (!seen.has(key)) { seen.add(key); columns.push(key); }
    }
  }

  // A column is numeric (right-aligned, tabular-nums) when its first
  // non-null displayed value is a number — values only, no model lookups.
  const numeric = new Map();
  for (const col of columns) {
    const probe = shown.find((row) => row[col] != null);
    numeric.set(col, typeof probe?.[col] === 'number');
  }

  const th = columns
    .map((c) => `<th${numeric.get(c) ? ' class="is-num"' : ''}>${esc(c)}</th>`)
    .join('');
  const rows = shown
    .map((row) => `<tr>${columns
      .map((c) => `<td${numeric.get(c) ? ' class="is-num"' : ''}>${renderCell(row[c])}</td>`)
      .join('')}</tr>`)
    .join('');

  const footer = values.length > DATA_ROW_CAP
    ? `<div class="sh-data-foot">showing ${fmtCount(DATA_ROW_CAP)} of ${fmtCount(values.length)} rows</div>`
    : '';

  return dataHead(model, `${fmtCount(values.length)} rows`)
    + `<div class="sh-data-scroll"><table class="sh-data-table">`
    + `<thead><tr>${th}</tr></thead><tbody>${rows}</tbody>`
    + `</table></div>`
    + footer;
}

function renderData(result) {
  if (!result || result.vega_lite_spec === null) {
    // Degrade exactly like the Chart view so the two segments agree.
    if (result?.errors?.length) { showErrorOverlay(result.errors); }
    else { showEmptyState({ title: 'Nothing to render yet', sub: 'The compile returned no chart and no errors.' }); }
    return;
  }

  hideErrorOverlay();
  elPreview.style.display = 'none';
  elDataView.style.display = 'flex';

  const model = result.model ?? null;
  const values = result.vega_lite_spec?.data?.values;

  if (values === undefined) {
    // Either resolution was skipped (warning present) or the inline source
    // file is missing (silent no-op in resolve_model_data) — say which.
    const skipped = (result.warnings ?? []).find(
      (w) => typeof w === 'string' && w.startsWith('Data resolution skipped:'),
    );
    elDataView.innerHTML = dataMessage(
      model,
      'no rows',
      skipped ?? 'No data resolved for this chart — the compiled spec has no inline rows.',
    );
    return;
  }

  if (values.length === 0) {
    elDataView.innerHTML = dataMessage(model, '0 rows', 'The query returned 0 rows.');
    return;
  }

  elDataView.innerHTML = buildDataTable(model, values);
}

// ─── Render Dispatcher ────────────────────────────────────
function renderPreview(result) {
  if (state.currentView === 'data') {
    renderData(result);
  } else {
    renderChart(result);
  }
}

// ─── Init ──────────────────────────────────────────────────
export function initPreview() {
  showEmptyState({
    title: 'Open a file to see its preview',
    sub: 'Charts render live as you type. Pick a YAML file from the explorer.',
  });

  document.addEventListener('shelves:non-chart-file', (e) => {
    state.lastCompileResult = null;
    const name = e.detail.path ? e.detail.path.split('/').pop() : 'This file';
    showEmptyState({
      title: 'No preview for this file',
      sub: `${name} isn't a chart or dashboard, so there's nothing to render. Edits still save normally.`,
    });
    renderPreviewHeader('chart');
  });

  document.addEventListener('shelves:compile-result', (e) => {
    if (state.dashboardMode) return;
    if (!resultIsForCurrentFile(e.detail)) return;  // watcher broadcast for another file (SHE-49)
    state.lastCompileResult = e.detail;
    renderPreview(state.lastCompileResult);
    updateAmbientTime();
    renderPreviewHeader('chart');
  });

  document.addEventListener('shelves:view-change', () => {
    if (state.dashboardMode) return;
    if (state.lastCompileResult) {
      renderPreview(state.lastCompileResult);
    }
  });

  document.addEventListener('shelves:compile-start', () => {
    hideErrorOverlay();          // stale errors shouldn't linger over the veil
    beginLoadingState();         // no display:none anywhere anymore
  });

  // preview.js owns the veil; every result-ish event for the OPEN file ends
  // it — a watcher broadcast for another file must not end a veil that is
  // still waiting on the local compile (SHE-49). Dashboards end on
  // `dashboard-rendered`, not `dashboard-result`: the result only proves the
  // HTML string exists, the iframe still has to render it (SHE-67);
  // dashboard.js guarantees exactly one rendered event per accepted result.
  // A superseded compile never dispatches an end event (compileSeq-guarded
  // returns), which is fine: the newer compile's start already re-armed the
  // timer and its result will end the veil.
  ['shelves:compile-result', 'shelves:dashboard-rendered', 'shelves:non-chart-file']
    .forEach(ev => document.addEventListener(ev, (e) => {
      if (!resultIsForCurrentFile(e.detail)) return;
      endLoadingState();
    }));

  let resizeTimer = null;
  new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (state.lastCompileResult && !state.dashboardMode && state.currentView === 'chart') {
        if (state.vegaView) {
          try { state.vegaView.resize().run(); } catch (_) { renderChart(state.lastCompileResult); }
        } else {
          renderChart(state.lastCompileResult);
        }
      }
    }, 200);
  }).observe(elChartContainer);
}
