// ─── Editor Module ─────────────────────────────────────────
// Monaco editor setup, compile, save, resize.

import {
  state, COMPILE_DEBOUNCE_MS, STORAGE_KEY_SETTINGS, STORAGE_KEY_PANE_WIDTH,
  updateStatusBar, updateBreadcrumb, resultIsForCurrentFile,
} from './state.js';
import { recordNavigation, navigateBack, navigateForward } from './nav.js';

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
let _editorFailed = false;    // lets openFile bail before its probe fetch
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
    _editorFailed = true;
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
        // Vendored same-origin bundle (static/vendor/), built from
        // monaco-yaml@5.5.1's root yaml.worker.js WITH monaco-editor@0.52.2 —
        // the same version the main editor pins below. The previous jsdelivr
        // `/+esm` worker silently bundled monaco-editor@0.33.0 (below
        // monaco-yaml's own >=0.36 peer range): the 0.33 worker protocol
        // choked on 0.52's handshake ("e is not iterable"), Monaco fell back
        // to a main-thread worker that crashed the same way, and every
        // monaco-yaml diagnostic was dead. Same-origin also drops the blob
        // indirection the cross-origin CDN worker needed (SHE-48/SHE-77).
        return new Worker('/static/vendor/monaco-yaml-worker-5.5.1.min.js');
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
      // Squiggle colors from the design system, so errors and warnings read
      // distinctly instead of Monaco's near-identical defaults (SHE-101).
      'editorError.foreground': '#A33B2A',               // --danger
      'editorWarning.foreground': '#A8751F',             // --warning
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
    // Typing means the save outcome was seen and the user moved on — the
    // failed/saved line yields to normal compile status; the dirty dot still
    // communicates unsaved state (SHE-65).
    if (state.saveStatus === 'failed' || state.saveStatus === 'saved') {
      state.saveStatus = null;
      state.saveError = null;
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

  // Back/forward while focus is in the editor (SHE-40). This deliberately
  // shadows Monaco's outdent/indent defaults — recorded decision: navigation
  // wins; Tab/Shift+Tab still indent/outdent YAML.
  state.editor.addCommand(
    monaco.KeyMod.CtrlCmd | monaco.KeyCode.BracketLeft,
    () => navigateBack(),
  );
  state.editor.addCommand(
    monaco.KeyMod.CtrlCmd | monaco.KeyCode.BracketRight,
    () => navigateForward(),
  );

  // Closing/reloading the tab with unsaved changes must prompt (SHE-51).
  // preventDefault shows the browser's generic dialog; custom text is ignored.
  window.addEventListener('beforeunload', (e) => {
    if (state.currentFile?.dirty) {
      e.preventDefault();
      e.returnValue = '';
    }
  });

  document.addEventListener('shelves:file-change', (e) => {
    const msg = e.detail;
    // Deleted-on-disk tracking (SHE-51). The buffer stays open and editable;
    // Cmd+S recreates the file (and clears the notice).
    if (state.currentFile && msg.path === state.currentFile.path) {
      if (msg.event === 'deleted') {
        state.fileDeleted = true;
        updateBreadcrumb(state.currentFile.path, state.currentFile.dirty);
        updateStatusBar();
        return;                    // do NOT fall through to the reload fetch
      }
      if (state.fileDeleted && (msg.event === 'created' || msg.event === 'modified')) {
        state.fileDeleted = false; // resurrected externally
        updateBreadcrumb(state.currentFile.path, state.currentFile.dirty);
        updateStatusBar();
      }
    }
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

  document.addEventListener('shelves:dashboard-result', (e) => {
    // Dashboard warnings (filter options that would not resolve, truncated
    // domains, per-sheet compile notices) carry no line info, so they land as
    // file-level markers — same treatment applyCompileMarkers gives chart
    // warnings. Dashboard errors are plain strings and are skipped by that
    // function's object guard; they stay in the preview overlay.
    // The status bar is NOT touched here: dashboard.js owns the counters for
    // dashboard results (SHE-50) and feeds them straight from the payload.
    if (!resultIsForCurrentFile(e.detail)) return;
    applyCompileMarkers(e.detail);
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
    // Chart /compile returns positioned warning objects (line/col like errors,
    // SHE-101); the dashboard route still returns plain strings — both land
    // here, so handle either shape. A locless object (line == null) falls back
    // to the top of the file, same as a string.
    if (typeof warn === 'object' && warn !== null && (warn.msg || warn.message)) {
      const body = warn.msg ?? warn.message;
      const displayLoc = warn.display_loc ? warn.display_loc.join('.') : '';
      const msg = displayLoc ? `${displayLoc} — ${body}` : body;
      const line = warn.line ?? 1;
      markers.push({
        severity: monaco.MarkerSeverity.Warning,
        message: msg,
        startLineNumber: line,
        startColumn: warn.col ?? 1,
        endLineNumber: line,
        endColumn: warn.col != null ? warn.col + 1 : model.getLineMaxColumn(line),
      });
    } else {
      markers.push({
        severity: monaco.MarkerSeverity.Warning,
        message: typeof warn === 'string' ? warn : String(warn),
        startLineNumber: 1,
        startColumn: 1,
        endLineNumber: 1,
        endColumn: model.getLineMaxColumn(1),
      });
    }
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
/**
 * Open a file into the editor.
 * @param {string} path
 * @param {{fromHistory?: boolean}} [opts]  fromHistory: don't re-record (SHE-40)
 * @returns {Promise<'opened'|'cancelled'|'not-found'|'no-editor'|'error'>}
 */
export async function openFile(path, opts = {}) {
  if (state.currentFile?.path === path) return 'opened';      // same file: no-op
  if (_editorFailed) return 'no-editor';  // known-dead editor: nothing below can help

  // Probe the file BEFORE the dirty-buffer confirm (SHE-51). GET /file is
  // side-effect-free, and confirming first meant a since-deleted target
  // consumed a "discard" answer without acting on it — nav.js's prune loop
  // then re-entered here and asked again, once per pruned entry. Probing
  // first, a walk over dead entries prompts exactly once, for the file that
  // actually opens. No veil is armed yet, so failures here need no paired
  // compile-result to terminate one.
  let resp;
  try {
    resp = await fetch(`/file?path=${encodeURIComponent(path)}`);
  } catch (e) {
    console.error('[shelves] openFile error:', e);
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { vega_lite_spec: null, errors: [String(e)], warnings: [], path: null },
    }));
    return 'error';
  }
  if (resp.status === 404) {
    // Only a definite 404 reports 'not-found' — nav.js permanently prunes
    // history entries on it, so a transient failure (5xx on a mid-write
    // read, permissions) must map to 'error' instead, which keeps the entry.
    console.warn('[shelves] file not found:', path);
    return 'not-found';
  }
  if (!resp.ok) {
    const reason = (await resp.text().catch(() => '')) || `HTTP ${resp.status}`;
    console.error('[shelves] openFile failed:', path, reason);
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { vega_lite_spec: null, errors: [`Could not open ${path}: ${reason}`], warnings: [], path: null },
    }));
    return 'error';
  }

  // Dirty-buffer guard (SHE-51): still before anything arms a veil or
  // compile state, so a cancel leaves the session exactly as it was.
  if (state.currentFile?.dirty) {
    const ok = window.confirm(`Discard unsaved changes to ${state.currentFile.path}?`);
    if (!ok) return 'cancelled';
  }
  // No editor, no open: wait for Monaco (a click during boot), and if the
  // editor failed to load, the boot error card already explains the state —
  // don't arm a veil that nothing will ever terminate.
  try {
    await editorReady;
  } catch {
    return 'no-editor';
  }
  try {
    state.compiling = true;
    updateStatusBar();
    document.dispatchEvent(new CustomEvent('shelves:compile-start'));
    const { content } = await resp.json();
    state.currentFile = { path, dirty: false };
    state.fileDeleted = false;
    if (!opts.fromHistory) recordNavigation(path);
    _suppressDirty = true;
    state.editor.setValue(content);
    _suppressDirty = false;
    updateBreadcrumb(path, false);
    notifyActiveFileChanged();
    clearTimeout(state.compileTimer);
    if (_compileFn) _compileFn();
    return 'opened';
  } catch (e) {
    state.compiling = false;
    console.error('[shelves] openFile error:', e);
    document.dispatchEvent(new CustomEvent('shelves:compile-result', {
      detail: { vega_lite_spec: null, errors: [String(e)], warnings: [], path: null },
    }));
    return 'error';
  }
}

function notifyActiveFileChanged() {
  document.dispatchEvent(new CustomEvent('shelves:active-file-changed'));
}

// ─── Save (SHE-65) ────────────────────────────────────────
// The dirty flag clears ONLY on a confirmed 2xx — a rejected PUT used to
// resolve the fetch and clear dirty as if it saved. Feedback runs through
// state.saveStatus: 150ms-gated "Saving…" (fast saves stay silent), a 2s
// "Saved" flash, and a persistent "Save failed: <reason>".
const SAVE_PENDING_GATE_MS = 150;   // same patience gate as the compile veil
const SAVED_FLASH_MS = 2000;
let _saveGateTimer = null;
let _savedClearTimer = null;

export async function saveCurrentFile() {
  if (!state.currentFile) return;
  const content = state.editor.getValue();
  const path = state.currentFile.path;

  clearTimeout(_saveGateTimer);
  clearTimeout(_savedClearTimer);
  // A new attempt clears the previous outcome NOW — a stale "Save failed"
  // must not keep rendering through the 150ms gate (PR #61 r3566202195).
  if (state.saveStatus !== null) {
    state.saveStatus = null;
    state.saveError = null;
    updateStatusBar();
  }
  _saveGateTimer = setTimeout(() => {
    state.saveStatus = 'saving';
    updateStatusBar();
  }, SAVE_PENDING_GATE_MS);

  let ok = false;
  let reason = null;
  try {
    const resp = await fetch(`/file?path=${encodeURIComponent(path)}`, {
      method: 'PUT',
      body: content,
    });
    ok = resp.ok;
    if (!ok) reason = (await resp.text().catch(() => '')) || `HTTP ${resp.status}`;
  } catch (e) {
    reason = String(e);
  }
  clearTimeout(_saveGateTimer);

  if (ok) {
    // Only a CONFIRMED write clears dirty / arms the watcher-echo suppression.
    // The path check guards the file-switched-mid-save race: the old file's
    // save result must not clear the NEW file's dirty flag or repaint the
    // breadcrumb with the old path (PR #61 r3566202205). The status message
    // stays unconditional — recorded decision: it names no file.
    _lastSavePath = path;
    _lastSaveTs = Date.now();
    state.saveStatus = 'saved';
    state.saveError = null;
    if (state.currentFile?.path === path) {
      state.currentFile.dirty = false;
      state.fileDeleted = false;  // a confirmed write recreates a deleted file
      updateBreadcrumb(path, false);
    }
    updateStatusBar();
    _savedClearTimer = setTimeout(() => {
      if (state.saveStatus === 'saved') {
        state.saveStatus = null;
        updateStatusBar();
      }
    }, SAVED_FLASH_MS);
  } else {
    state.saveStatus = 'failed';
    state.saveError = reason;
    console.error('[shelves] save failed:', reason);
    updateStatusBar();   // dirty flag untouched; breadcrumb keeps the dot
  }
}

// ─── Settings ──────────────────────────────────────────────
function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY_SETTINGS) || '{}');
  } catch { return {}; }
}

// ─── Resize Handle ─────────────────────────────────────────
// Pointer-captured splitter on the sidebar-handle recipe (SHE-53/SHE-38):
// capture routes every pointer event to the handle, so drags survive fast
// moves, leaving the window, and the dashboard iframe — no overlay needed.
function initResizeHandle() {
  const handle = document.getElementById('resize-handle');
  const workspace = document.getElementById('workspace');
  const editorPane = document.getElementById('editor-pane');
  const EDITOR_MIN_PX = 200, PREVIEW_MIN_PX = 320, DEFAULT_PCT = 25;

  const saved = localStorage.getItem(STORAGE_KEY_PANE_WIDTH);
  if (saved) {
    document.documentElement.style.setProperty('--editor-width', saved + '%');
  }

  let dragging = false, rafId = null, pendingPct = null;

  function clampPct(pxWidth) {
    // pxWidth = desired editor-column width in px (cursor - editor pane left).
    // Measuring from the editor pane's own left edge (not the workspace's) is
    // what keeps the divider under the cursor whatever the sidebar state.
    const wsRect = workspace.getBoundingClientRect();
    const maxPx = wsRect.width - editorPane.getBoundingClientRect().left
                + wsRect.left - PREVIEW_MIN_PX - 1; // preview keeps its minimum
    const px = Math.max(EDITOR_MIN_PX, Math.min(maxPx, pxWidth));
    return (px / wsRect.width) * 100;   // --editor-width is a % of the workspace grid
  }

  handle.addEventListener('pointerdown', (e) => {
    dragging = true;
    handle.classList.add('dragging');
    handle.setPointerCapture(e.pointerId);   // survives fast drags + the dashboard iframe
    e.preventDefault();                       // no text selection while dragging
  });
  handle.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    pendingPct = clampPct(e.clientX - editorPane.getBoundingClientRect().left);
    if (rafId == null) rafId = requestAnimationFrame(() => {
      rafId = null;
      if (pendingPct != null)
        document.documentElement.style.setProperty('--editor-width', pendingPct + '%');
    });
  });
  // pointerup is not the only way a drag ends: touch scrolling, OS gestures,
  // or losing capture fire pointercancel/lostpointercapture instead, and the
  // drag must terminate on those too or the handle sticks in dragging mode.
  function endDrag(e) {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    try { handle.releasePointerCapture(e.pointerId); } catch (_) {}  // capture may already be gone
    const current = parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue('--editor-width')
    ) || DEFAULT_PCT;
    localStorage.setItem(STORAGE_KEY_PANE_WIDTH, current.toFixed(1));
  }
  handle.addEventListener('pointerup', endDrag);
  handle.addEventListener('pointercancel', endDrag);
  handle.addEventListener('lostpointercapture', endDrag);
  handle.addEventListener('dblclick', () => {
    document.documentElement.style.setProperty('--editor-width', DEFAULT_PCT + '%');
    localStorage.setItem(STORAGE_KEY_PANE_WIDTH, String(DEFAULT_PCT));
  });
}
