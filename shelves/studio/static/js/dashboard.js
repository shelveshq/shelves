// ─── Dashboard Module ──────────────────────────────────────
// Dashboard detection, compile, preview, component tree strip.

import { state, updateStatusBadge } from './state.js';
import { highlightJson, showErrorOverlay, hideErrorOverlay } from './preview.js';

const CANVAS_WIDTH = 1440;
const CANVAS_HEIGHT = 900;

const elPreview          = document.getElementById('preview');
const elJsonView         = document.getElementById('json-view');
const elDashboardPreview = document.getElementById('dashboard-preview');
const elDashboardIframe  = document.getElementById('dashboard-iframe');
const elTreeStrip        = document.getElementById('component-tree-strip');

let lastDashboardResult = null;

// ─── Dashboard Detection ──────────────────────────────────
export function isDashboardYaml(content) {
  const lines = content.split('\n').slice(0, 20);
  return lines.some(line => /^dashboard\s*:/.test(line));
}

// ─── Dashboard Compile ────────────────────────────────────
export async function compileDashboardContent() {
  const content = state.editor.getValue();
  if (!content.trim()) {
    document.dispatchEvent(new CustomEvent('shelves:dashboard-result', {
      detail: { html: null, errors: [], warnings: [], component_tree: [] },
    }));
    return;
  }
  try {
    const resp = await fetch('/compile-dashboard', { method: 'POST', body: content });
    const result = await resp.json();
    document.dispatchEvent(new CustomEvent('shelves:dashboard-result', { detail: result }));
    updateStatusBadge(result.errors ?? [], result.warnings ?? []);
  } catch (e) {
    console.error('[shelves] dashboard compile error:', e);
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

  const clickScript = `
    <script>
      document.addEventListener('click', function(e) {
        var el = e.target.closest('[data-chart-link]');
        if (el) {
          window.parent.postMessage({ type: 'sheet-click', link: el.dataset.chartLink }, '*');
        }
      });
    <\/script>
  `;
  elDashboardIframe.srcdoc = result.html + clickScript;

  scaleDashboardIframe();
  renderComponentTreeStrip(result.component_tree ?? []);
}

function scaleDashboardIframe() {
  const paneRect = elDashboardPreview.getBoundingClientRect();
  const availW = paneRect.width  - 32;
  const availH = paneRect.height - 32;
  if (availW <= 0 || availH <= 0) return;
  const scale = Math.min(availW / CANVAS_WIDTH, availH / CANVAS_HEIGHT);
  elDashboardIframe.style.transform = `scale(${scale})`;
}

// ─── Component Tree Strip ─────────────────────────────────
function renderComponentTreeStrip(tree) {
  elTreeStrip.innerHTML = '';
  if (!tree || tree.length === 0) {
    elTreeStrip.style.display = 'none';
    return;
  }
  elTreeStrip.style.display = 'flex';

  let prevDepth = null;
  for (let i = 0; i < tree.length; i++) {
    const node = tree[i];

    if (prevDepth !== null) {
      const sep = document.createElement('span');
      if (node.depth > prevDepth) {
        sep.className = 'tree-arrow';
        sep.textContent = '\u2192';
      } else {
        sep.className = 'tree-separator';
        sep.textContent = '\u00b7';
      }
      elTreeStrip.appendChild(sep);
    }

    const span = document.createElement('span');
    const label = node.type === 'sheet'
      ? (node.name || node.type)
      : node.type === 'vertical' ? 'container (v)'
      : node.type === 'horizontal' ? 'container (h)'
      : node.type;

    if (node.type === 'sheet') {
      span.className = 'tree-node tree-sheet';
      span.title = node.link || '';
      span.addEventListener('click', () => {
        if (node.link) window.shelvesStudio.openFile(node.link);
      });
    } else if (node.type === 'vertical' || node.type === 'horizontal') {
      span.className = 'tree-node tree-container';
    } else {
      span.className = 'tree-node tree-leaf';
    }

    span.textContent = label;
    elTreeStrip.appendChild(span);
    prevDepth = node.depth;
  }
}

// ─── Layout Switching ─────────────────────────────────────
export function applyDashboardLayout() {
  state.dashboardMode = true;
  document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
  const dashBtn = document.querySelector('.view-btn[data-view="dashboard"]');
  if (dashBtn) dashBtn.classList.add('active');
  state.currentView = 'dashboard';
  elTreeStrip.style.display = 'flex';
}

export function restoreChartLayout() {
  state.dashboardMode = false;
  document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
  const chartBtn = document.querySelector('.view-btn[data-view="chart"]');
  if (chartBtn) chartBtn.classList.add('active');
  state.currentView = 'chart';
  elTreeStrip.style.display = 'none';
  elDashboardPreview.style.display = 'none';
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
  // Rescale iframe on resize
  new ResizeObserver(scaleDashboardIframe).observe(elDashboardPreview);

  // Dashboard result → render
  document.addEventListener('shelves:dashboard-result', (e) => {
    lastDashboardResult = e.detail;
    renderDashboardView(lastDashboardResult);
  });

  // View toggle → re-render (only in dashboard mode)
  document.addEventListener('shelves:view-change', () => {
    if (!state.dashboardMode) return;
    if (lastDashboardResult) {
      renderDashboardView(lastDashboardResult);
    }
  });

  // Iframe click-through → open chart file
  window.addEventListener('message', (event) => {
    if (event.data?.type === 'sheet-click') {
      window.shelvesStudio.openFile(event.data.link);
    }
  });
}
