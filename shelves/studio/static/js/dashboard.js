// ─── Dashboard Module ──────────────────────────────────────
// Dashboard detection, compile, preview, zoom control.

import { state, updateStatusBar } from './state.js';
import { highlightJson, showErrorOverlay, hideErrorOverlay, renderPreviewHeader } from './preview.js';

const CANVAS_WIDTH = 1440;
const CANVAS_HEIGHT = 900;

const elPreview          = document.getElementById('preview');
const elJsonView         = document.getElementById('json-view');
const elDashboardPreview = document.getElementById('dashboard-preview');
const elDashboardIframe  = document.getElementById('dashboard-iframe');

let lastDashboardResult = null;
let dashboardZoom = 'fit';
let compileSeq = 0;

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
    updateStatusBar([], []);
    return;
  }
  try {
    const t0 = performance.now();
    const resp = await fetch('/compile-dashboard', { method: 'POST', body: content });
    if (seq !== compileSeq) return;
    const result = await resp.json();
    state.lastCompileTimeMs = Math.round(performance.now() - t0);
    state.compiling = false;
    document.dispatchEvent(new CustomEvent('shelves:dashboard-result', { detail: result }));
    updateStatusBar(result.errors ?? [], result.warnings ?? []);
  } catch (e) {
    if (seq !== compileSeq) return;
    state.compiling = false;
    document.dispatchEvent(new CustomEvent('shelves:dashboard-result', {
      detail: { html: null, errors: [String(e)], warnings: [], component_tree: [] },
    }));
    updateStatusBar([String(e)]);
  }
}

// ─── Dashboard Preview Rendering ──────────────────────────
function renderDashboardPreview(result) {
  elPreview.style.display = 'none';
  elJsonView.style.display = 'none';

  if (!result || result.html === null) {
    showErrorOverlay(result?.errors ?? ['Dashboard compile failed.']);
    elDashboardPreview.style.display = 'none';
    return;
  }

  hideErrorOverlay();
  elDashboardPreview.style.display = 'flex';
  elDashboardIframe.removeAttribute('srcdoc');
  void elDashboardIframe.offsetHeight;
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
    scale = Math.min(availW / CANVAS_WIDTH, availH / CANVAS_HEIGHT);
  }
  elDashboardIframe.style.transform = `scale(${scale})`;
}

export function setDashboardZoom(zoom) {
  dashboardZoom = zoom;
  scaleDashboardIframe();
}

// ─── Layout Switching ─────────────────────────────────────
export function applyDashboardLayout() {
  state.dashboardMode = true;
  state.currentView = 'dashboard';
  document.getElementById('preview-pane').classList.add('is-dashboard');
  renderPreviewHeader('dashboard');
}

export function restoreChartLayout() {
  state.dashboardMode = false;
  state.currentView = 'chart';
  document.getElementById('preview-pane').classList.remove('is-dashboard');
  elDashboardPreview.style.display = 'none';
  renderPreviewHeader('chart');
}

// ─── Dashboard View Rendering ─────────────────────────────
function renderDashboardView(result) {
  if (state.currentView === 'json') {
    elPreview.style.display = 'none';
    elDashboardPreview.style.display = 'none';
    hideErrorOverlay();
    elJsonView.style.display = 'block';
    elJsonView.innerHTML = highlightJson(JSON.stringify(result.component_tree, null, 2));
  } else {
    renderDashboardPreview(result);
  }
}

// ─── Init ──────────────────────────────────────────────────
export function initDashboard() {
  new ResizeObserver(scaleDashboardIframe).observe(elDashboardPreview);

  document.addEventListener('shelves:compile-start', () => {
    if (state.dashboardMode) {
      elDashboardPreview.style.display = 'none';
      hideErrorOverlay();
    }
  });

  document.addEventListener('shelves:dashboard-result', (e) => {
    lastDashboardResult = e.detail;
    renderDashboardView(lastDashboardResult);
  });

  document.addEventListener('shelves:view-change', () => {
    if (!state.dashboardMode) return;
    if (lastDashboardResult) {
      renderDashboardView(lastDashboardResult);
    }
  });

  document.addEventListener('shelves:dashboard-zoom', (e) => {
    setDashboardZoom(e.detail.zoom);
  });
}
