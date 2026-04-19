// ─── Preview Module ────────────────────────────────────────
// Chart rendering, JSON syntax highlighting, error overlay.

import { state } from './state.js';

const elPreview        = document.getElementById('preview');
const elChartContainer = document.getElementById('chart-container');
const elJsonView       = document.getElementById('json-view');
const elErrorOverlay   = document.getElementById('error-overlay');

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
  // Compile result → render (only when not in dashboard mode)
  document.addEventListener('shelves:compile-result', (e) => {
    if (state.dashboardMode) return;
    state.lastCompileResult = e.detail;
    renderPreview(state.lastCompileResult);
  });

  // View toggle → re-render (only when not in dashboard mode)
  document.addEventListener('shelves:view-change', () => {
    if (state.dashboardMode) return;
    if (state.lastCompileResult) {
      renderPreview(state.lastCompileResult);
    }
  });

  // Clear stale error overlays when switching files
  document.addEventListener('shelves:compile-start', () => {
    hideErrorOverlay();
    elPreview.style.display = '';
  });

  // Resize: use view.resize() to avoid full re-embed flicker
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
