// Runs editor.js under node and exercises the boot FAILURE path (SHE-64):
// the Monaco CDN import cannot resolve under node (https imports are
// unsupported), which is exactly the browser failure mode where the import
// rejects. initEditor must swallow the rejection (never propagate to the
// caller — a rejected top-level await in main.js used to blank the whole UI),
// paint the error card into #editor-boot, and openFile must bail out cleanly
// without arming a compile veil.
//
// Usage: node run_editor_boot.mjs
// Prints one JSON object of observations (asserted by
// tests/test_studio_editor_boot.py).

const els = new Map();

function stubEl(id) {
  if (!els.has(id)) {
    els.set(id, {
      id,
      style: {},
      innerHTML: '',
      textContent: '',
      className: '',
      removed: false,
      classList: {
        _set: new Set(),
        add(c) { this._set.add(c); },
        remove(c) { this._set.delete(c); },
        contains(c) { return this._set.has(c); },
      },
      remove() { this.removed = true; },
      addEventListener() {},
      getBoundingClientRect() { return { width: 0, height: 0, left: 0, top: 0 }; },
    });
  }
  return els.get(id);
}

const dispatched = [];
globalThis.document = {
  getElementById: stubEl,
  querySelector: (sel) => stubEl(`doc::${sel}`),
  documentElement: { style: { setProperty() {} } },
  addEventListener() {},
  dispatchEvent(ev) { dispatched.push(ev.type); },
};

globalThis.CustomEvent = class CustomEvent {
  constructor(type, opts) {
    this.type = type;
    this.detail = opts?.detail;
  }
};

globalThis.window = {};
globalThis.localStorage = { getItem: () => null, setItem() {} };

const fetchCalls = [];
globalThis.fetch = (...args) => {
  fetchCalls.push(args[0]);
  return Promise.reject(new Error('no network in harness'));
};

const { initEditor, openFile } = await import('../../shelves/studio/static/js/editor.js');

const out = {};
const boot = stubEl('editor-boot');

// initEditor must RESOLVE despite the failed CDN import (self-guarding).
let initThrew = false;
try {
  await initEditor();
} catch {
  initThrew = true;
}
out.initEditorPropagatedError = initThrew;
out.bootIsError = boot.classList.contains('is-error');
out.bootHtml = boot.innerHTML;

// A file click after editor failure: no throw, no fetch, no veil armed.
let openThrew = false;
try {
  await openFile('charts/a.yaml');
} catch {
  openThrew = true;
}
out.openFilePropagatedError = openThrew;
out.openFileFetchCount = fetchCalls.length;
out.openFileDispatched = dispatched;

console.log(JSON.stringify(out));
process.exit(0);  // the 20s load-timeout timer must not delay exit
