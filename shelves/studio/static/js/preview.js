// ─── Preview Module ────────────────────────────────────────
// Chart rendering, JSON syntax highlighting, error overlay, preview header.

import { state } from './state.js';

const elPreview        = document.getElementById('preview');
const elChartContainer = document.getElementById('chart-container');
const elJsonView       = document.getElementById('json-view');
const elErrorOverlay   = document.getElementById('error-overlay');

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
export function showErrorOverlay(errors) {
  elPreview.style.display = 'none';
  elJsonView.style.display = 'none';
  elErrorOverlay.style.display = 'block';

  const count = errors.length;
  const items = errors
    .map(e => `<li class="error-item">${String(e).replace(/</g, '&lt;')}</li>`)
    .join('');

  elErrorOverlay.innerHTML = `
    <div class="error-card">
      <div class="error-title">Validation Error${count !== 1 ? 's' : ''} (${count})</div>
      <ul style="margin:0;padding-left:16px">${items}</ul>
    </div>`;
}

export function hideErrorOverlay() {
  elErrorOverlay.style.display = 'none';
}

// ─── Chart Rendering ───────────────────────────────────────
async function renderChart(result) {
  elJsonView.style.display = 'none';

  if (!result || result.vega_lite_spec === null) {
    showErrorOverlay(result?.errors ?? ['No spec available.']);
    return;
  }

  hideErrorOverlay();
  elPreview.style.display = '';

  const containerSpec = Object.assign({}, result.vega_lite_spec, {
    width: 'container',
    height: 'container',
    autosize: { type: 'fit', contains: 'padding' },
  });

  const buf = document.createElement('div');
  buf.style.cssText = 'position:absolute;inset:0;visibility:hidden;';
  elChartContainer.appendChild(buf);

  try {
    const { view } = await window.vegaEmbed(buf, containerSpec, {
      actions: false,
      renderer: 'canvas',
    });
    if (state.vegaView) {
      try { state.vegaView.finalize(); } catch (_) {}
    }
    while (elChartContainer.firstChild !== buf) {
      elChartContainer.removeChild(elChartContainer.firstChild);
    }
    buf.style.cssText = 'width:100%;height:100%;';
    state.vegaView = view;
  } catch (e) {
    buf.remove();
    showErrorOverlay([String(e)]);
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
    hideErrorOverlay();
    if (state.dashboardMode) {
      elPreview.style.display = 'none';
    } else {
      elPreview.style.display = 'none';
      elJsonView.style.display = 'none';
    }
  });

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
