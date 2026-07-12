// PR #61 review follow-ups (Copilot r3566202195 / r3566202205): drives
// editor.js's saveCurrentFile under node with a controllable fetch to pin
// the two save-lifecycle races:
//   1. A new save attempt clears a prior 'failed' outcome IMMEDIATELY —
//      the stale failure line must not linger through the 150ms gate.
//   2. A save completing after the user switched files must not rewrite
//      the breadcrumb back to the old path.
//
// Usage: node run_save_race.mjs
// Prints one JSON object (asserted by tests/test_studio_save_status.py).

const els = new Map();

function stubEl(id) {
  if (!els.has(id)) {
    els.set(id, { id, className: '', textContent: '', innerHTML: '' });
  }
  return els.get(id);
}

globalThis.document = {
  getElementById: stubEl,
  querySelector: (sel) => stubEl(`doc::${sel}`),
  querySelectorAll: () => [],
  addEventListener() {},
  dispatchEvent() {},
};

globalThis.CustomEvent = class CustomEvent {
  constructor(type, opts) {
    this.type = type;
    this.detail = opts?.detail;
  }
};

globalThis.window = { addEventListener() {}, confirm: () => true };

// Controllable PUT: resolves with `nextOk` after `delayMs`.
let delayMs = 0;
let nextOk = true;
globalThis.fetch = (url, opts) => new Promise((resolve) => {
  setTimeout(() => resolve({
    ok: nextOk,
    status: nextOk ? 200 : 500,
    text: async () => 'boom',
  }), delayMs);
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const { state, updateBreadcrumb } = await import('../../shelves/studio/static/js/state.js');
const { saveCurrentFile } = await import('../../shelves/studio/static/js/editor.js');

state.editor = { getValue: () => 'sheet: X\ndata: y\n' };
const statusMsg = stubEl('doc::#statusbar .sh-status-msg');
const crumb = stubEl('doc::#header .sh-crumb');

const out = {};

// ── 1. New attempt clears a stale 'failed' outcome immediately ──
state.currentFile = { path: 'charts/a.yaml', dirty: true };
state.wsStatus = 'connected';
state.compiling = false;
state.saveStatus = 'failed';
state.saveError = 'previous failure';
delayMs = 60;
nextOk = true;
const p1 = saveCurrentFile();
out.statusRightAfterRetry = state.saveStatus;         // must not be 'failed'
out.msgRightAfterRetry = statusMsg.textContent;       // must not say Save failed
await p1;
out.statusAfterRetrySettles = state.saveStatus;       // 'saved'

// ── 2. File switch mid-save: breadcrumb must stay on the NEW file ──
state.saveStatus = null;
state.saveError = null;
state.currentFile = { path: 'charts/a.yaml', dirty: true };
delayMs = 80;
nextOk = true;
const p2 = saveCurrentFile();
await sleep(20);
// user switches files while the PUT is in flight
state.currentFile = { path: 'charts/b.yaml', dirty: false };
updateBreadcrumb('charts/b.yaml', false);
await p2;
await sleep(20);
out.crumbAfterLateSave = crumb.innerHTML;             // must show b.yaml, not a.yaml
out.newFileDirtyAfterLateSave = state.currentFile.dirty;  // stays false, untouched

console.log(JSON.stringify(out));
process.exit(0);
