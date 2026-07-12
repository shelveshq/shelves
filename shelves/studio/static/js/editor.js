// ─── Editor Module ─────────────────────────────────────────
// Monaco editor setup, compile, save, resize.

import {
  state, COMPILE_DEBOUNCE_MS, STORAGE_KEY_SETTINGS, STORAGE_KEY_PANE_WIDTH,
  updateStatusBar, updateBreadcrumb, resultIsForCurrentFile,
} from './state.js';

let _compileFn = null;
let _suppressDirty = false;
let _lastSavePath = null;
let _lastSaveTs = 0;
let compileSeq = 0;

// ─── Schema Routing (SHE-48) ──────────────────────────────
// The ChartSpec schema requires `sheet`/`data`, so applying it to every YAML
// buffer gives dashboards/models phantom "Missing property" markers. The
// schema is attached only while the open buffer classifies as chart YAML
// (shelves:buffer-kind from main.js's compile router).
let _monacoYamlHandle = null;   // return value of configureMonacoYaml
let _chartSchema = null;        // the fetched /schema JSON
let _schemaAttached = false;    // matches the initial configureMonacoYaml call

function setSchemaAttached(on) {
  if (!_monacoYamlHandle || !_chartSchema || on === _schemaAttached) return;
  _schemaAttached = on;
  // monaco-yaml v5's update() is async — fire-and-forget.
  _monacoYamlHandle.update({
    enableSchemaRequest: false,
    schemas: on ? [{
      uri: window.location.origin + '/schema',
      fileMatch: ['*'],
      schema: _chartSchema,
    }] : [],
  }).catch(console.warn);
}

export function setCompileFunction(fn) {
  _compileFn = fn;
}

// ─── Boot Lifecycle (SHE-64) ──────────────────────────────
// Boot is parallel: the rest of Studio never waits on Monaco. Anything that
// needs the editor (openFile) awaits `editorReady` instead; the promise
// settles exactly once — resolve on a working editor, reject on load
// failure/timeout, with the error card as the visible terminal state.
const EDITOR_LOAD_TIMEOUT_MS = 20000;

let _editorReadyResolve, _editorReadyReject;
const editorReady = new Promise((res, rej) => {
  _editorReadyResolve = res;
  _editorReadyReject = rej;
});
editorReady.catch(() => {});  // rejection is surfaced via the error card

function escText(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function hideEditorBoot() {
  document.getElementById('editor-boot')?.remove();
}

function showEditorBootError(e) {
  const boot = document.getElementById('editor-boot');
  if (!boot) return;
  boot.classList.add('is-error');
  boot.innerHTML = `
    <div class="error-card">
      <div class="error-title">Editor failed to load</div>
      <ul class="error-list">
        <li class="error-item">Monaco couldn't be fetched — check your connection or ad-blocker, then reload the page. Everything else (file tree, preview, terminal) keeps working.</li>
        <li class="error-item">${escText(e)}</li>
      </ul>
    </div>`;
}

export async function initEditor() {
  initResizeHandle();  // the pane splitter needs no Monaco — never gate it
  let timeoutId = null;
  const timeout = new Promise((_, rej) => {
    timeoutId = setTimeout(
      () => rej(new Error(`Timed out after ${EDITOR_LOAD_TIMEOUT_MS / 1000}s`)),
      EDITOR_LOAD_TIMEOUT_MS,
    );
  });
  try {
    await Promise.race([initMonacoEditor(), timeout]);
    hideEditorBoot();
    _editorReadyResolve();
  } catch (e) {
    // Without this guard a Monaco CDN failure used to reject main.js's
    // top-level await and blank the ENTIRE UI with no in-page error (SHE-64).
    console.error('[shelves] editor failed to load:', e);
    showEditorBootError(e);
    _editorReadyReject(e);
  } finally {
    clearTimeout(timeoutId);  // don't leave a 20s timer pending after settle
  }
}

async function initMonacoEditor() {
  const loader = (await import('https://cdn.jsdelivr.net/npm/@monaco-editor/loader@1.5.0/+esm')).default;
  const { configureMonacoYaml } = await import('https://cdn.jsdelivr.net/npm/monaco-yaml@5.5.1/+esm');

  window.MonacoEnvironment = {
    getWorker(_, label) {
      if (label === 'yaml') {
        // monaco-yaml v5 ships its worker at the package ROOT as an ES module.
        // The old `lib/esm/yaml.worker.js` path is a v4-era layout and 404s on
        // every 5.x, which blanked the whole editor (SHE-64).
        //
        // A Worker's top-level script must be SAME-ORIGIN — a cross-origin CDN
        // URL is rejected ("cannot be accessed from origin ..."), even with
        // { type: 'module' }. So we point the worker at a same-origin blob whose
        // module body `import`s the cross-origin CDN build: module imports (not
        // the worker script itself) ARE allowed cross-origin under CORS, which
        // jsdelivr serves. We use jsdelivr's `/+esm` build so the worker's bare
        // imports are rewritten to absolute URLs the module graph can resolve.
        // Version pinned (not the floating `@5` tag) to avoid the silent CDN
        // drift that caused this (see SHE-6 / SHE-76).
        const workerUrl = 'https://cdn.jsdelivr.net/npm/monaco-yaml@5.5.1/yaml.worker.js/+esm';
        const blob = new Blob([`import ${JSON.stringify(workerUrl)};`], { type: 'text/javascript' });
        return new Worker(URL.createObjectURL(blob), { type: 'module' });
      }
      // monaco-editor's own worker is a classic (UMD) script. A cross-origin
      // *classic* worker isn't allowed, so wrap it in a same-origin blob that
      // importScripts() the CDN URL.
      const editorUrl = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs/base/worker/workerMain.js';
      const blob = new Blob([`importScripts("${editorUrl}");`], { type: 'text/javascript' });
      return new Worker(URL.createObjectURL(blob));
    },
  };

  const settings = loadSettings();
  // Pin the monaco-editor build the loader fetches to the same version the
  // classic worker URL above names — the loader's own default is whatever its
  // release pinned and can drift apart from our worker pin (SHE-77).
  loader.config({
    paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs' },
  });
  const monaco = await loader.init();
  window._shelvesMonaco = monaco;

  // DS syntax tokens, resolved to hex — Monaco cannot read CSS variables.
  // Sources: colors_and_type.css --syntax-* ; studio/tokens.css bridge.
  monaco.editor.defineTheme('shelves', {
    base: 'vs',
    inherit: true,
    rules: [
      // Token names WITHOUT '#'. In Monaco's YAML tokenizer, mapping keys
      // tokenize as 'type', scalars as 'string'/'number', true/false/null as
      // 'keyword'.
      { token: 'type',    foreground: '3A6278' },  // keys    — --syntax-key
      { token: 'string',  foreground: '6B8E4E' },  // strings — --syntax-string
      { token: 'number',  foreground: 'B8531C' },  // numbers — --syntax-number (ochre)
      { token: 'keyword', foreground: '8B5A9F' },  // bool/null — --syntax-bool
      { token: 'comment', foreground: '9A968B' },  // --syntax-comment (ink-4)
    ],
    colors: {
      // Values WITH '#' in this map (yes, the asymmetry is real).
      'editor.background': '#FAF8F3',                    // --paper
      'editor.foreground': '#1A1916',                    // --syntax-plain (ink-10)
      'editorLineNumber.foreground': '#C9C5B8',          // --ink-2 (gutter)
      'editorLineNumber.activeForeground': '#3A3833',    // --ink-8
      'editorCursor.foreground': '#B8531C',              // --brand-ochre
      'editor.selectionBackground': '#F7E9DC',           // --brand-ochre-tint
      'editor.lineHighlightBackground': '#F7E9DC',       // studio design: active line = ochre tint
      'editor.lineHighlightBorder': '#00000000',         // kill the default box border on the active line
      'editorIndentGuide.background1': '#E8E4D8',        // --paper-edge
      'editorWidget.background': '#FFFFFF',              // autocomplete popup = paper-raised
      'editorWidget.border': '#E8E4D8',
      'editorSuggestWidget.selectedBackground': '#F7E9DC',
      'scrollbarSlider.background': '#0B0B0A26',
    },
  });

  try {
    _chartSchema = await fetch('/schema').then(r => r.json());
  } catch (e) {
    console.warn('[shelves] Could not load /schema for Monaco YAML:', e);
  }

  // Start with NO schema attached: the boot buffer is empty, and the first
  // shelves:buffer-kind (from the first compile after openFile) attaches the
  // ChartSpec schema only if the buffer is chart YAML (SHE-48).
  _monacoYamlHandle = configureMonacoYaml(monaco, {
    enableSchemaRequest: false,
    schemas: [],
  });

  document.addEventListener('shelves:buffer-kind', (e) => {
    setSchemaAttached(e.detail.kind === 'chart');
  });

  state.editor = monaco.editor.create(document.getElementById('editor'), {
    value: '',
    language: 'yaml',
    theme: 'shelves',
    fontFamily: "'JetBrains Mono', 'SF Mono', Menlo, monospace",
    fontLigatures: false,
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

  document.addEventListener('shelves:compile-result', (e) => {
    // Ignore broadcasts for a file other than the one currently open —
    // otherwise a watcher result for another file paints its markers
    // (at its line numbers) onto the active editor.
    if (!resultIsForCurrentFile(e.detail)) return;
    applyCompileMarkers(e.detail);
    syncMarkerCounts();
    updateStatusBar();
  });

  document.addEventListener('shelves:non-chart-file', () => {
    // No compile runs for non-chart YAML, so nothing else clears the previous
    // file's compile markers from the shared model — clear them here or the
    // status dot stays red and phantom squiggles linger.
    const model = state.editor?.getModel();
    if (model) monaco.editor.setModelMarkers(model, 'shelves-compile', []);
    syncMarkerCounts();
    updateStatusBar();
  });

  monaco.editor.onDidChangeMarkers((uris) => {
    const model = state.editor?.getModel();
    if (!model) return;
    if (!uris.some(u => u.toString() === model.uri.toString())) return;
    if (state.compiling) return;
    syncMarkerCounts();
    updateStatusBar();
  });
}

// Registered at module scope, not from initMonacoEditor: the sidebar renders
// (and is clickable) long before Monaco arrives now that boot is parallel —
// openFile itself awaits editorReady (SHE-64).
window.shelvesStudio = { openFile };

// ─── Compile Markers ──────────────────────────────────────
export function applyCompileMarkers(result) {
  if (!state.editor) return;
  const model = state.editor.getModel();
  if (!model) return;

  const monaco = window._shelvesMonaco;
  const markers = [];

  for (const err of (result.errors ?? [])) {
    if (typeof err === 'object' && (err.friendly_msg || err.msg)) {
      const displayLoc = err.display_loc ? err.display_loc.join('.') : '';
      const body = err.friendly_msg ?? err.msg;
      const tag = err.source === 'yaml' ? '[YAML] ' : err.source === 'dsl' ? '[DSL] ' : '';
      const msg = displayLoc
        ? `${tag}${displayLoc} — ${body}`
        : `${tag}${body}`;
      const line = err.line ?? 1;
      markers.push({
        severity: monaco.MarkerSeverity.Error,
        message: msg,
        startLineNumber: line,
        startColumn: err.col ?? 1,
        endLineNumber: line,
        endColumn: err.col != null ? err.col + 1 : model.getLineMaxColumn(line),
      });
    }
  }

  for (const warn of (result.warnings ?? [])) {
    markers.push({
      severity: monaco.MarkerSeverity.Warning,
      message: typeof warn === 'string' ? warn : String(warn),
      startLineNumber: 1,
      startColumn: 1,
      endLineNumber: 1,
      endColumn: model.getLineMaxColumn(1),
    });
  }

  monaco.editor.setModelMarkers(model, 'shelves-compile', markers);
}

// ─── Marker Counts ────────────────────────────────────────
function syncMarkerCounts() {
  const monaco = window._shelvesMonaco;
  const model = state.editor?.getModel();
  if (!monaco || !model) {
    state.markerErrors = 0;
    state.markerWarnings = 0;
    return;
  }
  const all = monaco.editor.getModelMarkers({ resource: model.uri });
  state.markerErrors = 0;
  state.markerWarnings = 0;
  for (const m of all) {
    if (m.severity === monaco.MarkerSeverity.Error) state.markerErrors++;
    else if (m.severity === monaco.MarkerSeverity.Warning) state.markerWarnings++;
  }
}

// ─── Compile ───────────────────────────────────────────────
export async function compileCurrentContent() {
  const seq = ++compileSeq;
  const content = state.editor.getValue();
  if (!content.trim()) {
    state.compiling = false;
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { vega_lite_spec: null, errors: [], warnings: [], path: state.currentFile?.path ?? null },
    }));
    return;
  }
  try {
    const t0 = performance.now();
    const resp = await fetch('/compile', { method: 'POST', body: content });
    if (seq !== compileSeq) return;
    const result = await resp.json();
    if (seq !== compileSeq) return;
    state.lastCompileTimeMs = Math.round(performance.now() - t0);
    state.compiling = false;
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { ...result, path: state.currentFile?.path ?? null },
    }));
  } catch (e) {
    if (seq !== compileSeq) return;
    state.compiling = false;
    console.error('[shelves] compile error:', e);
    // Network failure: dispatch a terminal result so the veil clears and the
    // overlay explains what happened.
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { vega_lite_spec: null, errors: [String(e)], warnings: [], path: state.currentFile?.path ?? null },
    }));
  }
}

// ─── Open File ────────────────────────────────────────────
export async function openFile(path) {
  // No editor, no open: wait for Monaco (a click during boot), and if the
  // editor failed to load, the boot error card already explains the state —
  // don't arm a veil that nothing will ever terminate.
  try {
    await editorReady;
  } catch {
    return;
  }
  try {
    state.compiling = true;
    updateStatusBar();
    document.dispatchEvent(new CustomEvent('shelves:compile-start'));
    const resp = await fetch(`/file?path=${encodeURIComponent(path)}`);
    if (!resp.ok) {
      console.warn('[shelves] file not found:', path);
      state.compiling = false;
      updateStatusBar();
      // Terminate the compile-start dispatched above, or the loading veil
      // sticks. Every start must pair with exactly one end event.
      document.dispatchEvent(new CustomEvent('shelves:compile-result', {
        detail: { vega_lite_spec: null, errors: [], warnings: [], path: null },
      }));
      return;
    }
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
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { vega_lite_spec: null, errors: [String(e)], warnings: [], path: null },
    }));
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
