// ─── Editor Module ─────────────────────────────────────────
// Monaco editor setup, compile, tab management, save, resize.

import {
  state, COMPILE_DEBOUNCE_MS, STORAGE_KEY_SETTINGS, STORAGE_KEY_PANE_WIDTH,
  updateStatusBadge,
} from './state.js';

// Late-bound compile function — set by main.js after all modules init
let _compileFn = null;

// Suppress dirty marking when programmatically setting editor value
let _suppressDirty = false;

// Self-echo suppression: ignore file-change events that echo our own saves
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

  // Fetch ChartSpec JSON Schema for YAML autocomplete + validation
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
    theme: 'vs-dark',
    minimap: { enabled: settings.minimap ?? true },
    wordWrap: (settings.wordWrap ?? true) ? 'on' : 'off',
    fontSize: settings.fontSize ?? 13,
    automaticLayout: true,
    scrollBeyondLastLine: false,
    renderLineHighlight: 'line',
    tabSize: 2,
  });

  // Debounced compile on every keystroke
  state.editor.onDidChangeModelContent(() => {
    if (state.currentFile && !_suppressDirty) {
      state.currentFile.dirty = true;
    }
    renderTabBar();
    clearTimeout(state.compileTimer);
    if (_compileFn) {
      state.compileTimer = setTimeout(_compileFn, COMPILE_DEBOUNCE_MS);
    }
  });

  // Cmd+S / Ctrl+S
  state.editor.addCommand(
    monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
    () => saveCurrentFile(),
  );

  // Reload editor content when file changes externally (not dirty)
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

  // Expose public API for sidebar and dashboard iframe
  window.shelvesStudio = { openFile };
}

// ─── Compile ───────────────────────────────────────────────
export async function compileCurrentContent() {
  const content = state.editor.getValue();
  if (!content.trim()) {
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { vega_lite_spec: null, errors: [], warnings: [], path: state.currentFile?.path ?? null },
    }));
    updateStatusBadge([]);
    return;
  }
  try {
    const resp = await fetch('/compile', { method: 'POST', body: content });
    const result = await resp.json();
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { ...result, path: state.currentFile?.path ?? null },
    }));
    updateStatusBadge(result.errors ?? [], result.warnings ?? []);
  } catch (e) {
    console.error('[shelves] compile error:', e);
  }
}

// ─── Tab Management ────────────────────────────────────────
export async function openFile(path) {
  const existing = state.tabs.find(t => t.path === path);
  if (existing) {
    state.currentFile = existing;
    document.dispatchEvent(new CustomEvent('shelves:compile-start'));
    const resp = await fetch(`/file?path=${encodeURIComponent(path)}`);
    if (resp.ok) {
      const { content } = await resp.json();
      _suppressDirty = true;
      state.editor.setValue(content);
      _suppressDirty = false;
    }
    renderTabBar();
    notifyActiveFileChanged();
    clearTimeout(state.compileTimer);
    if (_compileFn) _compileFn();
    return;
  }

  try {
    document.dispatchEvent(new CustomEvent('shelves:compile-start'));
    const resp = await fetch(`/file?path=${encodeURIComponent(path)}`);
    if (!resp.ok) { console.warn('[shelves] file not found:', path); return; }
    const { content } = await resp.json();
    const tab = { path, dirty: false };
    state.tabs.push(tab);
    state.currentFile = tab;
    _suppressDirty = true;
    state.editor.setValue(content);
    _suppressDirty = false;
    renderTabBar();
    notifyActiveFileChanged();
    clearTimeout(state.compileTimer);
    if (_compileFn) _compileFn();
  } catch (e) {
    console.error('[shelves] openFile error:', e);
  }
}

function switchToTab(path) {
  const tab = state.tabs.find(t => t.path === path);
  if (!tab) return;
  state.currentFile = tab;
  document.dispatchEvent(new CustomEvent('shelves:compile-start'));
  fetch(`/file?path=${encodeURIComponent(path)}`)
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (data) {
        _suppressDirty = true;
        state.editor.setValue(data.content);
        _suppressDirty = false;
      }
    })
    .catch(console.error);
  renderTabBar();
  notifyActiveFileChanged();
}

function closeTab(path) {
  const idx = state.tabs.findIndex(t => t.path === path);
  if (idx === -1) return;
  state.tabs.splice(idx, 1);
  if (state.currentFile?.path === path) {
    if (state.tabs.length > 0) {
      switchToTab(state.tabs[Math.max(0, idx - 1)].path);
    } else {
      state.currentFile = null;
      _suppressDirty = true;
      state.editor.setValue('');
      _suppressDirty = false;
      updateStatusBadge([]);
      document.getElementById('status-badge').textContent = 'Ready';
      document.getElementById('status-badge').className = '';
      notifyActiveFileChanged();
    }
  }
  renderTabBar();
}

export function renderTabBar() {
  const bar = document.getElementById('tab-bar');
  bar.innerHTML = '';
  for (const tab of state.tabs) {
    const el = document.createElement('div');
    el.className = 'tab' +
      (tab === state.currentFile ? ' active' : '') +
      (tab.dirty ? ' dirty' : '');
    el.title = tab.path;

    const name = document.createElement('span');
    name.textContent = tab.path.split('/').pop();
    el.appendChild(name);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'tab-close';
    closeBtn.textContent = '\u00d7';
    closeBtn.title = 'Close';
    closeBtn.onclick = (e) => { e.stopPropagation(); closeTab(tab.path); };
    el.appendChild(closeBtn);

    el.onclick = () => switchToTab(tab.path);
    bar.appendChild(el);
  }
}

// ─── Active File Notification ──────────────────────────────
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
    renderTabBar();
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
