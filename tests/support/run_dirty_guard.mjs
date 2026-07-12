// Runs editor.js + state.js under node with a minimal DOM stub and exercises
// the unsaved-changes protections (SHE-51):
//   - openFile over a dirty buffer asks confirm() and honors Cancel
//   - opening the already-open file is a no-op (no prompt)
//   - state.fileDeleted renders the status-bar notice + breadcrumb badge,
//     below compiling but above the marker counts
//
// Usage: node run_dirty_guard.mjs
// Prints one JSON object of observations (asserted by
// tests/test_studio_dirty_guard.py).

const els = new Map();

function stubEl(id) {
  if (!els.has(id)) {
    els.set(id, { id, className: '', textContent: '', innerHTML: '' });
  }
  return els.get(id);
}

const listeners = new Map();
let compileStarts = 0;

globalThis.document = {
  getElementById: stubEl,
  querySelector: (sel) => stubEl(`doc::${sel}`),
  querySelectorAll: () => [],
  addEventListener(type, fn) {
    if (!listeners.has(type)) listeners.set(type, []);
    listeners.get(type).push(fn);
  },
  dispatchEvent(ev) {
    if (ev.type === 'shelves:compile-start') compileStarts += 1;
    for (const fn of listeners.get(ev.type) ?? []) fn(ev);
  },
};

globalThis.CustomEvent = class CustomEvent {
  constructor(type, opts) {
    this.type = type;
    this.detail = opts?.detail;
  }
};

const confirmCalls = [];
let confirmAnswer = false;
globalThis.window = {
  addEventListener() {},
  confirm(msg) {
    confirmCalls.push(msg);
    return confirmAnswer;
  },
};

let fetchCalls = 0;
globalThis.fetch = async () => {
  fetchCalls += 1;
  return { ok: true, json: async () => ({ content: '' }) };
};

const { state, updateStatusBar, updateBreadcrumb } = await import(
  '../../shelves/studio/static/js/state.js'
);
await import('../../shelves/studio/static/js/editor.js');
const { openFile } = globalThis.window.shelvesStudio;

const statusDot = stubEl('doc::#statusbar .sh-status-dot');
const statusMsg = stubEl('doc::#statusbar .sh-status-msg');
const crumb = stubEl('doc::#header .sh-crumb');

const out = {};

// ── openFile guards ──
state.currentFile = { path: 'charts/a.yaml', dirty: true };

// Same file: no prompt, no reload.
openFile('charts/a.yaml');
out.samePathPrompted = confirmCalls.length;
out.samePathFetches = fetchCalls;

// Different file, user cancels: buffer and current file unchanged, no
// compile-start armed (a cancel must leave no veil pending). Raced against a
// timeout: without the guard, openFile hangs on editorReady (never settles in
// this harness) instead of returning.
confirmAnswer = false;
out.cancelSettled = await Promise.race([
  openFile('charts/b.yaml').then(() => true),
  new Promise((r) => setTimeout(() => r(false), 250)),
]);
out.cancelPrompt = confirmCalls[confirmCalls.length - 1] ?? null;
out.cancelPromptCount = confirmCalls.length;
out.cancelKeptFile = state.currentFile?.path === 'charts/a.yaml';
out.cancelFetches = fetchCalls;
out.cancelCompileStarts = compileStarts;

// Clean buffer: no prompt (openFile proceeds to await editorReady, which
// never settles in this harness — don't await it).
state.currentFile = { path: 'charts/a.yaml', dirty: false };
openFile('charts/c.yaml');
out.cleanPromptCount = confirmCalls.length;

// ── fileDeleted rendering (state.js) ──
state.currentFile = { path: 'charts/a.yaml', dirty: true };
state.wsStatus = 'connected';
state.compiling = false;
state.saveStatus = null;
state.markerErrors = 5;
state.markerWarnings = 0;
state.fileDeleted = true;
updateStatusBar();
out.deletedDot = statusDot.className;
out.deletedMsg = statusMsg.textContent;

// An in-flight compile outranks the deletion notice.
state.compiling = true;
updateStatusBar();
out.compilingOverDeletedMsg = statusMsg.textContent;
state.compiling = false;

// Breadcrumb badge while deleted.
updateBreadcrumb('charts/a.yaml', true);
out.deletedCrumbHasBadge = crumb.innerHTML.includes('sh-crumb-deleted');

// Notice cleared: badge gone, counts take back the status line.
state.fileDeleted = false;
updateStatusBar();
updateBreadcrumb('charts/a.yaml', true);
out.clearedMsg = statusMsg.textContent;
out.clearedCrumbHasBadge = crumb.innerHTML.includes('sh-crumb-deleted');

console.log(JSON.stringify(out));
process.exit(0);  // openFile promises pending on editorReady must not block exit
