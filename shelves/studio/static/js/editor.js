// ─── Editor Module ─────────────────────────────────────────
// Monaco editor setup, compile, save, resize.

import {
  state, COMPILE_DEBOUNCE_MS, STORAGE_KEY_SETTINGS, STORAGE_KEY_PANE_WIDTH,
  updateStatusBar, updateBreadcrumb,
} from './state.js';

let _compileFn = null;
let _suppressDirty = false;
let _lastSavePath = null;
let _lastSaveTs = 0;

export function setCompileFunction(fn) {
  _compileFn = fn;
}

export async function initEditor() {
  const loader = (await import('https://cdn.jsdelivr.net/npm/@monaco-editor/loader@1.5.0/+esm')).default;
  const { configureMonacoYaml } = await import('https://cdn.jsdelivr.net/npm/monaco-yaml@5/+esm');

  window.MonacoEnvironment = {
    getWorker(_, label) {
      if (label === 'yaml') {
        const url = 'https://cdn.jsdelivr.net/npm/monaco-yaml@5/lib/esm/yaml.worker.js';
        const blob = new Blob([`importScripts("${url}");`], { type: 'text/javascript' });
        return new Worker(URL.createObjectURL(blob));
      }
      const editorUrl = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs/base/worker/workerMain.js';
      const blob = new Blob([`importScripts("${editorUrl}");`], { type: 'text/javascript' });
      return new Worker(URL.createObjectURL(blob));
    },
  };

  const settings = loadSettings();
  const monaco = await loader.init();

  let schema = null;
  try {
    schema = await fetch('/schema').then(r => r.json());
  } catch (e) {
    console.warn('[shelves] Could not load /schema for Monaco YAML:', e);
  }

  configureMonacoYaml(monaco, {
    enableSchemaRequest: false,
    schemas: schema ? [{
      uri: window.location.origin + '/schema',
      fileMatch: ['*'],
      schema,
    }] : [],
  });

  state.editor = monaco.editor.create(document.getElementById('editor'), {
    value: '',
    language: 'yaml',
    theme: 'vs',
    minimap: { enabled: settings.minimap ?? true },
    wordWrap: (settings.wordWrap ?? true) ? 'on' : 'off',
    fontSize: settings.fontSize ?? 13,
    automaticLayout: true,
    scrollBeyondLastLine: false,
    renderLineHighlight: 'line',
    tabSize: 2,
  });

  state.editor.onDidChangeModelContent(() => {
    if (state.currentFile && !_suppressDirty) {
      state.currentFile.dirty = true;
    }
    updateBreadcrumb(state.currentFile?.path ?? null, state.currentFile?.dirty ?? false);
    clearTimeout(state.compileTimer);
    if (_compileFn) {
      state.compileTimer = setTimeout(_compileFn, COMPILE_DEBOUNCE_MS);
    }
  });

  state.editor.addCommand(
    monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
    () => saveCurrentFile(),
  );

  document.addEventListener('shelves:file-change', (e) => {
    const msg = e.detail;
    if (state.currentFile && state.currentFile.path === msg.path && !state.currentFile.dirty) {
      if (msg.path === _lastSavePath && (Date.now() - _lastSaveTs) < 2000) return;
      fetch(`/file?path=${encodeURIComponent(msg.path)}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data) {
            _suppressDirty = true;
            const model = state.editor.getModel();
            const selections = state.editor.getSelections();
            state.editor.executeEdits('shelves-file-reload', [{
              range: model.getFullModelRange(),
              text: data.content,
            }], selections);
            _suppressDirty = false;
            if (_compileFn) _compileFn();
          }
        })
        .catch(console.error);
    }
  });

  initResizeHandle();

  window.shelvesStudio = { openFile };
}

// ─── Compile ───────────────────────────────────────────────
export async function compileCurrentContent() {
  const content = state.editor.getValue();
  if (!content.trim()) {
    state.compiling = false;
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { vega_lite_spec: null, errors: [], warnings: [], path: state.currentFile?.path ?? null },
    }));
    updateStatusBar([]);
    return;
  }
  try {
    const t0 = performance.now();
    const resp = await fetch('/compile', { method: 'POST', body: content });
    const result = await resp.json();
    state.lastCompileTimeMs = Math.round(performance.now() - t0);
    state.compiling = false;
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { ...result, path: state.currentFile?.path ?? null },
    }));
    updateStatusBar(result.errors ?? [], result.warnings ?? []);
  } catch (e) {
    state.compiling = false;
    console.error('[shelves] compile error:', e);
  }
}

// ─── Open File ────────────────────────────────────────────
export async function openFile(path) {
  try {
    state.compiling = true;
    updateStatusBar();
    document.dispatchEvent(new CustomEvent('shelves:compile-start'));
    const resp = await fetch(`/file?path=${encodeURIComponent(path)}`);
    if (!resp.ok) { console.warn('[shelves] file not found:', path); return; }
    const { content } = await resp.json();
    state.currentFile = { path, dirty: false };
    _suppressDirty = true;
    state.editor.setValue(content);
    _suppressDirty = false;
    updateBreadcrumb(path, false);
    notifyActiveFileChanged();
    clearTimeout(state.compileTimer);
    if (_compileFn) _compileFn();
  } catch (e) {
    state.compiling = false;
    console.error('[shelves] openFile error:', e);
  }
}

function notifyActiveFileChanged() {
  document.dispatchEvent(new CustomEvent('shelves:active-file-changed'));
}

// ─── Save ──────────────────────────────────────────────────
async function saveCurrentFile() {
  if (!state.currentFile) return;
  const content = state.editor.getValue();
  try {
    await fetch(`/file?path=${encodeURIComponent(state.currentFile.path)}`, {
      method: 'PUT',
      body: content,
    });
    state.currentFile.dirty = false;
    _lastSavePath = state.currentFile.path;
    _lastSaveTs = Date.now();
    updateBreadcrumb(state.currentFile.path, false);
  } catch (e) {
    console.error('[shelves] save error:', e);
  }
}

// ─── Settings ──────────────────────────────────────────────
function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY_SETTINGS) || '{}');
  } catch { return {}; }
}

// ─── Resize Handle ─────────────────────────────────────────
function initResizeHandle() {
  const handle = document.getElementById('resize-handle');
  const workspace = document.getElementById('workspace');

  const saved = localStorage.getItem(STORAGE_KEY_PANE_WIDTH);
  if (saved) {
    document.documentElement.style.setProperty('--editor-width', saved + '%');
  }

  let dragging = false;

  handle.addEventListener('mousedown', (e) => {
    dragging = true;
    handle.classList.add('dragging');
    e.preventDefault();
  });

  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const rect = workspace.getBoundingClientRect();
    let pct = ((e.clientX - rect.left) / rect.width) * 100;
    pct = Math.max(15, Math.min(85, pct));
    document.documentElement.style.setProperty('--editor-width', pct + '%');
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    const current = parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue('--editor-width')
    ) || 50;
    localStorage.setItem(STORAGE_KEY_PANE_WIDTH, current.toFixed(1));
  });
}
