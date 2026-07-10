// ─── Preview Module ────────────────────────────────────────
// Chart rendering, JSON syntax highlighting, error overlay, preview header.

import { state } from './state.js';

const elPreview        = document.getElementById('preview');
const elChartContainer = document.getElementById('chart-container');
const elJsonView       = document.getElementById('json-view');
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
        <button class="sh-seg-btn${state.currentView === 'json' ? ' is-active' : ''}" data-view="json">JSON</button>
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

// ─── JSON Syntax Highlighting ──────────────────────────────
export function highlightJson(json) {
  const escaped = json
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  return escaped
    .replace(/("(?:\\.|[^"\\])*")(\s*:)/g,
      '<span class="json-key">$1</span>$2')
    .replace(/:\s*("(?:\\.|[^"\\])*")/g,
      ': <span class="json-string">$1</span>')
    .replace(/:\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)/g,
      ': <span class="json-number">$1</span>')
    .replace(/:\s*(true|false)/g,
      ': <span class="json-bool">$1</span>')
    .replace(/:\s*(null)/g,
      ': <span class="json-null">$1</span>');
}

// ─── Error Overlay ─────────────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                  .replace(/"/g, '&quot;');
}

export function showErrorOverlay(errors, title = "Can't compile this chart") {
  elPreview.style.display = 'none';
  elJsonView.style.display = 'none';
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
  elJsonView.style.display = 'none';
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
  elJsonView.style.display = 'none';

  if (!result || result.vega_lite_spec === null) {
    // Defensive: watcher broadcasts can still deliver a null-spec/no-error
    // result until SHE-49 lands.
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

// ─── JSON View Rendering ──────────────────────────────────
function renderJson(result) {
  elPreview.style.display = 'none';
  hideErrorOverlay();
  elJsonView.style.display = 'block';

  if (!result || result.vega_lite_spec === null) {
    const errText = (result?.errors ?? ['No spec.']).join('\n');
    elJsonView.textContent = errText;
    return;
  }

  const pretty = JSON.stringify(result.vega_lite_spec, null, 2);
  elJsonView.innerHTML = highlightJson(pretty);
}

// ─── Render Dispatcher ────────────────────────────────────
function renderPreview(result) {
  if (state.currentView === 'json') {
    renderJson(result);
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

  // preview.js owns the veil; every result-ish event ends it. A superseded
  // compile never dispatches an end event (compileSeq-guarded returns), which
  // is fine: the newer compile's start already re-armed the timer and its
  // result will end the veil.
  ['shelves:compile-result', 'shelves:dashboard-result', 'shelves:non-chart-file']
    .forEach(ev => document.addEventListener(ev, endLoadingState));

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
