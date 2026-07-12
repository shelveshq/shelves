// Runs state.js under node with a minimal DOM stub and exercises the
// save-status branches of updateStatusBar (SHE-65):
//   - saveStatus 'saving' / 'saved' / 'failed' render their own status line
//   - compiling outranks saveStatus (precedence: compiling > saveStatus > counts)
//   - a failed save with no reason falls back to 'unknown error'
//
// Usage: node run_save_status.mjs
// Prints one JSON object of observations (asserted by
// tests/test_studio_save_status.py).

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

const { state, updateStatusBar } = await import('../../shelves/studio/static/js/state.js');

const statusDot = stubEl('doc::#statusbar .sh-status-dot');
const statusMsg = stubEl('doc::#statusbar .sh-status-msg');

const out = {};

state.currentFile = { path: 'charts/a.yaml', dirty: true };
state.wsStatus = 'connected';
state.compiling = false;
state.dashboardMode = false;
state.markerErrors = 0;
state.markerWarnings = 0;

// ── Saving (gate elapsed) ──
state.saveStatus = 'saving';
updateStatusBar();
out.savingDot = statusDot.className;
out.savingMsg = statusMsg.textContent;

// ── Failed save: persistent error line, named reason ──
state.saveStatus = 'failed';
state.saveError = 'disk full';
updateStatusBar();
out.failedDot = statusDot.className;
out.failedMsg = statusMsg.textContent;

// ── Failed save without a reason ──
state.saveError = null;
updateStatusBar();
out.failedNoReasonMsg = statusMsg.textContent;

// ── Saved flash ──
state.saveStatus = 'saved';
state.saveError = null;
updateStatusBar();
out.savedDot = statusDot.className;
out.savedMsg = statusMsg.textContent;

// ── Precedence: compiling outranks saveStatus ──
state.compiling = true;
state.saveStatus = 'failed';
state.saveError = 'boom';
updateStatusBar();
out.compilingOverSaveMsg = statusMsg.textContent;

// ── Save failure does NOT mask error counts once cleared ──
state.compiling = false;
state.saveStatus = null;
state.saveError = null;
state.markerErrors = 2;
updateStatusBar();
out.countsAfterClearMsg = statusMsg.textContent;

console.log(JSON.stringify(out));
