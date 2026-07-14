// Runs editor.js + state.js under node with a minimal DOM stub and exercises
// the unsaved-changes protections (SHE-51):
//   - openFile over a dirty buffer asks confirm() and honors Cancel
//   - opening the already-open file is a no-op (no prompt)
//   - a missing (404) or failing (5xx) target never consumes the confirm:
//     the file is probed BEFORE the prompt, 404 → 'not-found', 5xx → 'error'
//   - the real openFile wired into nav.js's prune loop prompts exactly once
//     when backing over a deleted entry with a dirty buffer (SHE-40 review)
//   - state.fileDeleted renders the status-bar notice + breadcrumb badge,
//     below compiling but above the marker counts
//
// Usage: node run_dirty_guard.mjs
// Prints one JSON object of observations (asserted by
// tests/test_studio_dirty_guard.py).

const els = new Map();

function stubEl(id) {
  if (!els.has(id)) {
    els.set(id, {
      id, className: '', textContent: '', innerHTML: '', disabled: false,
      addEventListener() {},   // nav.js wires click handlers on its buttons
    });
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
let fetchRoutes = {};   // path fragment (unencoded) → status; default 200
globalThis.fetch = async (url) => {
  fetchCalls += 1;
  let status = 200;
  for (const [frag, s] of Object.entries(fetchRoutes)) {
    if (String(url).includes(encodeURIComponent(frag))) status = s;
  }
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ content: '' }),
    text: async () => 'read exploded',
  };
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
// compile-start armed (a cancel must leave no veil pending). The side-effect-
// free probe fetch runs BEFORE the prompt (so cancelFetches is 1, not 0), but
// nothing downstream of the confirm may have happened. Raced against a
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

// Clean buffer: no prompt. openFile parks at editorReady (never settles in
// this harness), so don't await it — but DO flush it past the probe fetch and
// the dirty check before the next scenario re-dirties the buffer.
state.currentFile = { path: 'charts/a.yaml', dirty: false };
openFile('charts/c.yaml');
await new Promise((r) => setImmediate(r));
out.cleanPromptCount = confirmCalls.length;

// ── probe-before-confirm (SHE-40 review) ──
// A 404 target returns 'not-found' WITHOUT consuming the dirty confirm —
// answering "discard" for a file that then fails to open left the discard
// un-acted-on and made nav.js's prune loop prompt once per pruned entry.
state.currentFile = { path: 'charts/a.yaml', dirty: true };
fetchRoutes = { 'charts/gone.yaml': 404 };
let promptsBefore = confirmCalls.length;
out.notFoundStatus = await openFile('charts/gone.yaml');
out.notFoundPrompts = confirmCalls.length - promptsBefore;
out.notFoundKeptFile = state.currentFile?.path === 'charts/a.yaml';

// Only a definite 404 is 'not-found' (nav.js prunes history on it); a 5xx —
// mid-write read, permissions — is 'error' and must not prompt either.
fetchRoutes = { 'charts/flaky.yaml': 500 };
promptsBefore = confirmCalls.length;
out.serverErrorStatus = await openFile('charts/flaky.yaml');
out.serverErrorPrompts = confirmCalls.length - promptsBefore;
fetchRoutes = {};

// ── nav prune walk: the REAL openFile prompts at most once ──
// Regression for the SHE-40 double-confirm: dirty buffer, back over a deleted
// entry. The prune loop re-enters openFile; only the entry that actually
// opens may prompt. navigateBack hangs at editorReady after the confirm
// (never settles here), so observe after a flush instead of awaiting it.
const { initNav, navigateBack } = await import(
  '../../shelves/studio/static/js/nav.js'
);
initNav({ openFile });
state.nav.stack = ['charts/a.yaml', 'charts/dead.yaml', 'charts/z.yaml'];
state.nav.index = 2;
state.currentFile = { path: 'charts/z.yaml', dirty: true };
fetchRoutes = { 'charts/dead.yaml': 404 };
confirmAnswer = true;
promptsBefore = confirmCalls.length;
navigateBack();
await new Promise((r) => setTimeout(r, 50));
out.navPrunePrompts = confirmCalls.length - promptsBefore;
out.navPrunePromptedFor = confirmCalls[confirmCalls.length - 1] ?? null;
out.navPruneStack = [...state.nav.stack];
fetchRoutes = {};
confirmAnswer = false;

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
