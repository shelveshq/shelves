// Runs nav.js under node with a fake openFile and verifies the back/forward
// file-navigation history (SHE-40): stack semantics, pruning of deleted
// files, dirty-cancel abort, button disabled states, and the keyboard/mouse
// bindings (including the terminal and defaultPrevented exclusions).
//
// Usage: node run_nav_history.mjs
// Prints one JSON object keyed by scenario (asserted by
// tests/test_studio_nav_history.py).

// ── DOM / env stubs (pattern: run_theme_event.mjs + run_dirty_guard.mjs) ──
const els = new Map();
function stubEl(id) {
  if (!els.has(id)) {
    els.set(id, {
      id,
      disabled: false,
      handlers: {},
      addEventListener(type, fn) {
        (this.handlers[type] ??= []).push(fn);
      },
      contains: () => false,
    });
  }
  return els.get(id);
}

const bodyEl = { id: 'body' };
const termChild = { id: 'terminal-child' };
stubEl('terminal-panel').contains = (el) => el === termChild;

const docListeners = new Map();
globalThis.document = {
  getElementById: stubEl,
  querySelector: () => null,
  addEventListener(type, fn) {
    if (!docListeners.has(type)) docListeners.set(type, []);
    docListeners.get(type).push(fn);
  },
  dispatchEvent() {},
};

const { state } = await import('../../shelves/studio/static/js/state.js');
const {
  initNav, recordNavigation, renameNavEntries, updateNavButtons,
  navigateBack, navigateForward,
} = await import('../../shelves/studio/static/js/nav.js');

// ── fake openFile ──
let script = {};       // path -> status | () => Promise<status>; default 'opened'
const calls = [];      // [path, fromHistory]
async function fakeOpenFile(path, opts = {}) {
  calls.push([path, opts.fromHistory === true]);
  const s = script[path];
  const status = typeof s === 'function' ? await s() : (s ?? 'opened');
  if (status === 'opened') state.currentFile = { path, dirty: false };
  return status;
}

initNav({ openFile: fakeOpenFile });

// A user-driven open is fakeOpenFile + recordNavigation — exactly what the
// real editor.js::openFile does on success.
async function userOpen(path) {
  const status = await fakeOpenFile(path);
  if (status === 'opened') recordNavigation(path);
}

function resetScenario() {
  state.nav.stack = [];
  state.nav.index = -1;
  state.currentFile = null;
  script = {};
  calls.length = 0;
}

const flush = () => new Promise((r) => setImmediate(r));
const btnBack = stubEl('nav-back');
const btnFwd = stubEl('nav-forward');

async function fireKey(opts) {
  const e = {
    metaKey: false, ctrlKey: false, shiftKey: false, altKey: false,
    key: '', target: bodyEl, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; },
    ...opts,
  };
  for (const fn of docListeners.get('keydown') ?? []) fn(e);
  await flush();
}

async function fireMouse(button) {
  const e = { button, preventDefault() {} };
  for (const fn of docListeners.get('mouseup') ?? []) fn(e);
  await flush();
}

const A = 'charts/a.yaml', B = 'charts/b.yaml', C = 'charts/c.yaml', D = 'charts/d.yaml';
const out = {};

// ── walk: A→B→C, back×2, forward×2, ends disable, fromHistory flags ──
{
  resetScenario();
  await userOpen(A); await userOpen(B); await userOpen(C);
  const walk = {};
  walk.afterOpens = { stack: [...state.nav.stack], index: state.nav.index };
  const baseline = calls.length;
  await navigateBack();
  walk.afterBack1 = { current: state.currentFile.path, index: state.nav.index };
  await navigateBack();
  walk.afterBack2 = {
    current: state.currentFile.path, index: state.nav.index,
    backDisabled: btnBack.disabled, fwdDisabled: btnFwd.disabled,
  };
  const before = calls.length;
  await navigateBack();                       // at the start: must be a no-op
  walk.noopCalls = calls.length - before;
  await navigateForward();
  walk.afterFwd1 = { current: state.currentFile.path, index: state.nav.index };
  await navigateForward();
  walk.afterFwd2 = {
    current: state.currentFile.path, index: state.nav.index,
    backDisabled: btnBack.disabled, fwdDisabled: btnFwd.disabled,
  };
  walk.historyCallsFromHistory =
    calls.slice(baseline).every(([, fromHistory]) => fromHistory);
  out.walk = walk;
}

// ── truncate: a new open drops the forward branch ──
{
  resetScenario();
  await userOpen(A); await userOpen(B); await userOpen(C);
  await navigateBack(); await navigateBack();   // at A
  await userOpen(D);
  out.truncate = { stack: [...state.nav.stack], index: state.nav.index };
}

// ── buttons: disabled states + click wiring ──
{
  resetScenario();
  updateNavButtons();
  const buttons = { empty: { back: btnBack.disabled, fwd: btnFwd.disabled } };
  await userOpen(A);
  buttons.oneFile = { back: btnBack.disabled, fwd: btnFwd.disabled };
  await userOpen(B);
  buttons.twoFiles = { back: btnBack.disabled, fwd: btnFwd.disabled };
  btnBack.handlers.click[0]();                  // the real wiring, not navigateBack()
  await flush();
  buttons.clickNavigates = state.currentFile.path === A;
  out.buttons = buttons;
}

// ── keyboard: chords, terminal skip, defaultPrevented skip, exact chord ──
{
  resetScenario();
  await userOpen(A); await userOpen(B);
  const kb = {};
  let before = calls.length;
  await fireKey({ metaKey: true, key: '[' });
  kb.back = calls.length - before;
  kb.backLanded = state.currentFile.path === A;
  before = calls.length;
  await fireKey({ metaKey: true, key: ']' });
  kb.fwd = calls.length - before;
  kb.fwdLanded = state.currentFile.path === B;
  before = calls.length;
  await fireKey({ ctrlKey: true, key: '[', target: termChild });
  kb.terminalSkipped = calls.length === before;
  before = calls.length;
  await fireKey({ metaKey: true, key: '[', defaultPrevented: true });
  kb.preventedSkipped = calls.length === before;
  before = calls.length;
  await fireKey({ metaKey: true, key: '[', shiftKey: true });
  kb.shiftSkipped = calls.length === before;
  out.keyboard = kb;
}

// ── mouse: buttons 3/4 ──
{
  resetScenario();
  await userOpen(A); await userOpen(B);
  const mouse = {};
  let before = calls.length;
  await fireMouse(3);
  mouse.back = calls.length - before;
  mouse.backLanded = state.currentFile.path === A;
  before = calls.length;
  await fireMouse(4);
  mouse.fwd = calls.length - before;
  mouse.fwdLanded = state.currentFile.path === B;
  out.mouse = mouse;
}

// ── prune: a deleted file is dropped and back falls through ──
{
  resetScenario();
  await userOpen(A); await userOpen(B); await userOpen(C);
  script[B] = 'not-found';
  await navigateBack();
  out.prune = {
    current: state.currentFile.path,
    stack: [...state.nav.stack],
    index: state.nav.index,
  };
}

// ── cancel: dirty-confirm rejection keeps the position ──
{
  resetScenario();
  await userOpen(A); await userOpen(B);
  script[A] = 'cancelled';
  await navigateBack();
  out.cancel = {
    current: state.currentFile.path,
    stack: [...state.nav.stack],
    index: state.nav.index,
  };
}

// ── dedupe: re-recording the current file doesn't push ──
{
  resetScenario();
  await userOpen(A);
  recordNavigation(A);
  out.dedupe = { len: state.nav.stack.length };
}

// ── rename: history entries follow a rename ──
{
  resetScenario();
  await userOpen(A); await userOpen(B);
  renameNavEntries(A, 'charts/a2.yaml');
  await navigateBack();
  out.rename = {
    stack: [...state.nav.stack],
    openedWith: calls.at(-1)[0],
    current: state.currentFile.path,
  };
}

// ── cap: stack bounded at NAV_STACK_MAX (100), oldest dropped ──
{
  resetScenario();
  for (let i = 0; i < 105; i++) await userOpen(`charts/p${i}.yaml`);
  out.cap = {
    len: state.nav.stack.length,
    first: state.nav.stack[0],
    index: state.nav.index,
  };
}

// ── busy: a second trigger during an in-flight navigation is ignored ──
{
  resetScenario();
  await userOpen(A); await userOpen(B);
  let release;
  script[A] = () => new Promise((r) => { release = r; });
  const before = calls.length;
  const p1 = navigateBack();          // hangs inside openFile
  await flush();
  await navigateBack();               // busy: returns without calling openFile
  out.busy = { callsDuring: calls.length - before };
  release('opened');
  await p1;
  out.busy.current = state.currentFile.path;
}

// ── error: transient failure aborts without pruning ──
{
  resetScenario();
  await userOpen(A); await userOpen(B);
  script[A] = 'error';
  await navigateBack();
  out.error = {
    current: state.currentFile.path,
    stackLen: state.nav.stack.length,
    index: state.nav.index,
  };
}

console.log(JSON.stringify(out));
process.exit(0);
