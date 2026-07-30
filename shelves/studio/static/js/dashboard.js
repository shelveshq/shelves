// ─── Dashboard Module ──────────────────────────────────────
// Dashboard detection, compile, preview, zoom control.

import { state, updateStatusBar, resultIsForCurrentFile } from './state.js';
import { showErrorOverlay, hideErrorOverlay, renderPreviewHeader } from './preview.js';

const DEFAULT_CANVAS_W = 1440;
const DEFAULT_CANVAS_H = 900;

// Declared canvas size of the current dashboard (KAN-298). Updated from each
// compile result; falls back to the defaults for error/empty results.
let canvasW = DEFAULT_CANVAS_W;
let canvasH = DEFAULT_CANVAS_H;

const elPreview          = document.getElementById('preview');
const elDataView         = document.getElementById('data-view');
const elDashboardPreview = document.getElementById('dashboard-preview');
const elDashboardStage   = document.getElementById('dashboard-stage');
const elDashboardIframe  = document.getElementById('dashboard-iframe');

let lastDashboardResult = null;
let dashboardZoom = 'fit';
let compileSeq = 0;

// SHE-92: parameter overrides accumulated from control changes in the iframe.
// Keyed by param name → string value. Cleared on file switch.
const paramOverrides = {};
const PARAM_DEBOUNCE_MS = 300;
let paramDebounceTimer = null;

// ─── Rendered Signal (SHE-67) ─────────────────────────────
// A dashboard result only means the HTML *string* exists — the iframe still
// has to parse it, fetch Vega from the CDN, and render every sheet. The
// loading veil therefore ends on `shelves:dashboard-rendered`, dispatched
// when the composed page posts {type:'shelves:rendered'} (after its embed
// promises settle), with load+timeout fallbacks so the veil can never stick.
const RENDERED_FALLBACK_MS = 15000;  // absolute cap from srcdoc assignment
const RENDERED_AFTER_LOAD_MS = 3000; // iframe loaded but no signal arrived

let awaitingRendered = false;
let awaitingRenderedPath = null;  // file the armed signal belongs to
let renderedTimer = null;

function armRenderedFallback(ms) {
  clearTimeout(renderedTimer);
  renderedTimer = setTimeout(signalDashboardRendered, ms);
}

function signalDashboardRendered() {
  clearTimeout(renderedTimer);
  renderedTimer = null;
  if (!awaitingRendered) return;
  awaitingRendered = false;
  // Stamp the path captured when the result was accepted: a slow iframe's
  // late signal must not pass preview.js's resultIsForCurrentFile guard and
  // end a veil armed for a DIFFERENT file opened meanwhile (PR#60 review).
  document.dispatchEvent(new CustomEvent('shelves:dashboard-rendered', {
    detail: { path: awaitingRenderedPath },
  }));
}

function disarmRenderedSignal() {
  clearTimeout(renderedTimer);
  renderedTimer = null;
  awaitingRendered = false;
  awaitingRenderedPath = null;
}

// ─── Dashboard Detection ──────────────────────────────────
export function isDashboardYaml(content) {
  const lines = content.split('\n').slice(0, 20);
  return lines.some(line => /^dashboard\s*:/.test(line));
}

// ─── Dashboard Compile ────────────────────────────────────
export async function compileDashboardContent() {
  const seq = ++compileSeq;
  const content = state.editor.getValue();
  if (!content.trim()) {
    state.compiling = false;
    document.dispatchEvent(new CustomEvent('shelves:dashboard-result', {
      detail: { html: null, errors: [], warnings: [], component_tree: [] },
    }));
    return;
  }
  try {
    const t0 = performance.now();
    const headers = {};
    if (Object.keys(paramOverrides).length > 0) {
      headers['X-Shelves-Params'] = JSON.stringify(paramOverrides);
    }
    const resp = await fetch('/compile-dashboard', { method: 'POST', body: content, headers });
    if (seq !== compileSeq) return;
    const result = await resp.json();
    state.lastCompileTimeMs = Math.round(performance.now() - t0);
    state.compiling = false;
    document.dispatchEvent(new CustomEvent('shelves:dashboard-result', { detail: result }));
  } catch (e) {
    if (seq !== compileSeq) return;
    state.compiling = false;
    document.dispatchEvent(new CustomEvent('shelves:dashboard-result', {
      detail: { html: null, errors: [String(e)], warnings: [], component_tree: [] },
    }));
  }
}

// ─── Dashboard Preview Rendering ──────────────────────────
function renderDashboardPreview(result) {
  elPreview.style.display = 'none';
  elDataView.style.display = 'none';

  if (!result || result.html === null) {
    showErrorOverlay(result?.errors, "Can't compile this dashboard");
    elDashboardPreview.style.display = 'none';
    signalDashboardRendered();  // error overlay paints synchronously
    return;
  }

  hideErrorOverlay();
  elDashboardPreview.style.display = 'flex';

  // Pin the iframe to the dashboard's DECLARED canvas size (KAN-298). Falls
  // back to defaults when the result omits canvas (error results).
  canvasW = result.canvas?.width  ?? DEFAULT_CANVAS_W;
  canvasH = result.canvas?.height ?? DEFAULT_CANVAS_H;
  elDashboardIframe.style.width  = `${canvasW}px`;
  elDashboardIframe.style.height = `${canvasH}px`;

  // Direct srcdoc assignment keeps the old document painted until the new
  // one is ready; the old remove+reflow blanked the iframe for a frame.
  if (awaitingRendered) armRenderedFallback(RENDERED_FALLBACK_MS);
  elDashboardIframe.srcdoc = result.html;
  scaleDashboardIframe();
}

function scaleDashboardIframe() {
  const paneRect = elDashboardPreview.getBoundingClientRect();
  const availW = paneRect.width  - 48;
  const availH = paneRect.height - 48;
  if (availW <= 0 || availH <= 0) return;

  let scale;
  if (dashboardZoom === '100') {
    scale = 1;
  } else if (dashboardZoom === '50') {
    scale = 0.5;
  } else {
    scale = Math.min(availW / canvasW, availH / canvasH);
  }

  // Size the stage to the SCALED footprint so the pane has real content to
  // scroll. A CSS transform scales only the iframe's pixels, not its layout
  // box, and the iframe is position:absolute — without this the pane can
  // never scroll and the overflow is clipped (KAN-298 addendum).
  elDashboardStage.style.width  = `${canvasW * scale}px`;
  elDashboardStage.style.height = `${canvasH * scale}px`;

  elDashboardIframe.style.transform = `scale(${scale})`;
}

export function setDashboardZoom(zoom) {
  dashboardZoom = zoom;
  scaleDashboardIframe();
}

// ─── Layout Switching ─────────────────────────────────────
export function applyDashboardLayout() {
  clearParamOverrides();
  state.dashboardMode = true;
  state.currentView = 'dashboard';
  document.getElementById('preview-pane').classList.add('is-dashboard');
  renderPreviewHeader('dashboard');
}

export function restoreChartLayout() {
  state.dashboardMode = false;
  state.dashboardErrors = 0;
  state.dashboardWarnings = 0;
  // A signal armed for the departed dashboard must not fire into chart mode
  // via a late postMessage or fallback timer (PR#60 review).
  disarmRenderedSignal();
  clearParamOverrides();
  state.currentView = 'chart';
  document.getElementById('preview-pane').classList.remove('is-dashboard');
  elDashboardPreview.style.display = 'none';
  renderPreviewHeader('chart');
}

function clearParamOverrides() {
  for (const k of Object.keys(paramOverrides)) delete paramOverrides[k];
  clearTimeout(paramDebounceTimer);
  paramDebounceTimer = null;
}

// ─── Init ──────────────────────────────────────────────────
export function initDashboard() {
  new ResizeObserver(scaleDashboardIframe).observe(elDashboardPreview);

  document.addEventListener('shelves:compile-start', () => {
    // No hiding on start — the stale dashboard stays visible under the veil
    // (preview.js) until the new result paints.
    if (state.dashboardMode) {
      hideErrorOverlay();
    }
  });

  document.addEventListener('shelves:dashboard-result', (e) => {
    // Watcher broadcasts stamp the changed file's path; local compiles don't.
    // A foreign file must not repaint the preview, and a broadcast for the
    // open file only applies while the dashboard surface is active (SHE-49).
    if (!resultIsForCurrentFile(e.detail)) return;
    if ((e.detail.path ?? null) !== null && !state.dashboardMode) return;
    lastDashboardResult = e.detail;
    // This handler owns the status bar for dashboard results — local compiles
    // and watcher broadcasts alike (SHE-50). Dashboard errors have no Monaco
    // markers, so the counters are fed directly from the result.
    state.dashboardErrors = (e.detail.errors ?? []).length;
    state.dashboardWarnings = (e.detail.warnings ?? []).length;
    updateStatusBar();
    // Every result arms exactly one rendered signal (SHE-37 invariant):
    // the error path fires it synchronously inside renderDashboardPreview;
    // the iframe path fires it on the page's postMessage or a fallback timer.
    // Broadcasts carry the file's path; local compiles are stamped with the
    // open file so a late signal can be attributed (see signalDashboardRendered).
    awaitingRendered = true;
    awaitingRenderedPath = e.detail.path ?? state.currentFile?.path ?? null;
    renderDashboardPreview(lastDashboardResult);
  });

  window.addEventListener('message', (e) => {
    if (e.source !== elDashboardIframe.contentWindow) return;
    if (e.data?.type === 'shelves:rendered') {
      signalDashboardRendered();
      return;
    }
    if (e.data?.type === 'shelves:param-change' && e.data.param) {
      paramOverrides[e.data.param] = String(e.data.value ?? '');
      clearTimeout(paramDebounceTimer);
      paramDebounceTimer = setTimeout(() => {
        state.compiling = true;
        updateStatusBar();
        document.dispatchEvent(new CustomEvent('shelves:compile-start'));
        compileDashboardContent();
      }, PARAM_DEBOUNCE_MS);
    }
  });

  elDashboardIframe.addEventListener('load', () => {
    // load fires before the embeds settle; give the page's own rendered
    // signal a grace window, then clear anyway (composed HTML predating the
    // postMessage hook would otherwise pin the veil to the absolute cap).
    if (awaitingRendered) armRenderedFallback(RENDERED_AFTER_LOAD_MS);
  });

  document.addEventListener('shelves:view-change', () => {
    if (!state.dashboardMode) return;
    if (lastDashboardResult) {
      renderDashboardPreview(lastDashboardResult);
    }
  });

  document.addEventListener('shelves:dashboard-zoom', (e) => {
    setDashboardZoom(e.detail.zoom);
  });
}
