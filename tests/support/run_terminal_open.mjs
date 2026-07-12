// Runs terminal.js under node and exercises the SHE-47 open path:
//   mode "open"    — the panel opens BEFORE the terminal is created, the
//                    terminal opens synchronously (not gated on ws.onopen),
//                    auth precedes resize on the socket, and every failure
//                    path (1008 auth reject, abnormal close, shell exit)
//                    writes a VISIBLE message into the opened terminal.
//   mode "libfail" — the xterm CDN import rejects; the toggle must still
//                    open the panel and render a readable error card.
//
// Usage: node run_terminal_open.mjs <open|libfail>
// Prints one JSON object of observations (asserted by
// tests/test_studio_terminal_ui.py).

const mode = process.argv[2] ?? 'open';

globalThis.__termEvents = [];
const events = globalThis.__termEvents;

if (mode === 'open') {
  globalThis.__shelvesXtermSrc = new URL('./fake_xterm.mjs', import.meta.url).href;
  globalThis.__shelvesXtermFitSrc = globalThis.__shelvesXtermSrc;
} else {
  globalThis.__shelvesXtermSrc = new URL('./no-such-module.mjs', import.meta.url).href;
  globalThis.__shelvesXtermFitSrc = globalThis.__shelvesXtermSrc;
}

// ── DOM stubs ──
const allElements = [];

function makeEl(tag = 'div') {
  const el = {
    tag,
    id: '',
    className: '',
    innerHTML: '',
    textContent: '',
    title: '',
    dataset: {},
    style: {},
    children: [],
    removed: false,
    listeners: new Map(),
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
      toggle(c, force) { force ? this._set.add(c) : this._set.delete(c); },
    },
    appendChild(child) { this.children.push(child); child.parent = el; },
    remove() { this.removed = true; },
    addEventListener(type, fn) {
      if (!el.listeners.has(type)) el.listeners.set(type, []);
      el.listeners.get(type).push(fn);
    },
    fire(type, ev) { for (const fn of el.listeners.get(type) ?? []) fn(ev); },
    querySelector(sel) {
      const cls = sel.replace(/^\./, '');
      return el.children.find((c) => !c.removed && c.className.split(' ').includes(cls)) ?? null;
    },
    setPointerCapture() {},
    releasePointerCapture() {},
  };
  allElements.push(el);
  return el;
}

const byId = new Map();
function getEl(id) {
  if (!byId.has(id)) {
    const el = makeEl();
    el.id = id;
    byId.set(id, el);
  }
  return byId.get(id);
}

const panel = getEl('terminal-panel');
panel.classList.add('collapsed');
// Record the visibility flip so ordering vs term-open is assertable.
const realRemove = panel.classList.remove.bind(panel.classList);
panel.classList.remove = (c) => {
  if (c === 'collapsed' && panel.classList.contains('collapsed')) events.push('panel-open');
  realRemove(c);
};

function isTab(el) {
  return !el.removed && el.className.split(' ').includes('terminal-tab');
}

globalThis.document = {
  getElementById: getEl,
  createElement: (tag) => makeEl(tag),
  querySelector(sel) {
    if (sel.startsWith('meta[name="shelves-terminal-token"]')) return { content: 'tok-123' };
    const m = sel.match(/^\.terminal-tab\[data-term-id="(\d+)"\]$/);
    if (m) return allElements.find((el) => isTab(el) && String(el.dataset.termId) === m[1]) ?? null;
    return null;
  },
  querySelectorAll(sel) {
    if (sel === '.terminal-tab') return allElements.filter(isTab);
    return [];
  },
  addEventListener() {},
};

globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.location = { protocol: 'http:', host: '127.0.0.1:8089' };
globalThis.ResizeObserver = class { observe() {} disconnect() {} };

const sockets = [];
globalThis.WebSocket = class FakeWebSocket {
  static OPEN = 1;
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this.closeCalled = false;
    sockets.push(this);
    events.push('ws-created');
  }
  send(data) { this.sent.push(JSON.parse(data)); }
  close() { this.closeCalled = true; this.readyState = 3; }
};

const out = { mode, events };

const { initTerminal, toggleTerminalPanel } = await import(
  '../../shelves/studio/static/js/terminal.js'
);

let initError = null;
try {
  await initTerminal();
} catch (e) {
  initError = String(e);
}
out.initErrored = initError !== null;

const container = getEl('terminal-container');

if (mode === 'libfail') {
  // ── CDN import failed: toggle must still show the panel + error card ──
  toggleTerminalPanel();
  out.panelOpened = !panel.classList.contains('collapsed');
  const card = container.querySelector('.terminal-lib-error');
  out.errorCardText = card ? card.textContent : null;
  console.log(JSON.stringify(out));
  process.exit(0);
}

// ── mode "open" ──
const { instances } = await import('./fake_xterm.mjs');

// 1. Toggle: panel first, then a synchronously opened terminal, then the WS.
toggleTerminalPanel();
out.panelHeight = panel.style.height;
out.orderPanelOpen = events.indexOf('panel-open');
out.orderTermOpen = events.indexOf('term-open');
out.orderWsCreated = events.indexOf('ws-created');
out.fitAfterOpen = events.indexOf('fit') > events.indexOf('term-open');

const ws1 = sockets[0];
const term1 = instances[0];
out.termOpenedBeforeWsOpen = term1.element !== null && ws1.sent.length === 0;

// 2. Socket opens: auth (with the meta token) must precede resize.
ws1.readyState = 1;
ws1.onopen();
out.firstMsg = ws1.sent[0];
out.secondMsgType = ws1.sent[1]?.type;

// 3. Abnormal close (1006, no exit) writes a disconnect marker + dims the tab.
ws1.onclose({ code: 1006 });
out.disconnectLine = term1.lines.find((l) => l.includes('Disconnected')) ?? null;
out.tab1Dead = allElements.find(isTab).classList.contains('is-dead');

// 4. A 1008 close on a NEW terminal writes a visible, actionable auth message.
getEl('terminal-new').fire('click', {});
const ws2 = sockets[1];
const term2 = instances[1];
out.term2OpenedSynchronously = term2.element !== null;
ws2.readyState = 1;
ws2.onopen();
ws2.onclose({ code: 1008 });
out.authRejectLines = term2.lines.filter(
  (l) => l.includes('rejected') || l.includes('Reload the page'),
).length;
out.tab2Dead = allElements.filter(isTab)[1].classList.contains('is-dead');

// 5. Close tab 2 via its × — a later onclose must stay silent (userClosed).
const tab2 = allElements.filter(isTab)[1];
tab2.fire('click', { target: { classList: { contains: (c) => c === 'terminal-tab-close' } } });
const term2LinesBefore = term2.lines.length;
ws2.onclose({ code: 1006 });
out.userClosedSuppressed = term2.lines.length === term2LinesBefore;
out.term2Disposed = term2.disposed;

// 6. Shell exit is displayed; the clean 1000 close that may follow stays
//    silent — the exit line already told the story.
getEl('terminal-new').fire('click', {});
const ws3 = sockets[2];
const term3 = instances[2];
ws3.readyState = 1;
ws3.onopen();
ws3.onmessage({ data: JSON.stringify({ type: 'exit', code: 0 }) });
out.exitLine = term3.lines.find((l) => l.includes('Process exited')) ?? null;
const term3LinesAfterExit = term3.lines.length;
ws3.onclose({ code: 1000 });
out.silentCloseAfterExit = term3.lines.length === term3LinesAfterExit;

// 7. A bare 1000 close WITHOUT a preceding exit must still write a marker —
//    the server tearing down mid-session closes with a default 1000, and
//    silence there is a dead terminal with no message (PR #63 review).
getEl('terminal-new').fire('click', {});
const ws4 = sockets[3];
const term4 = instances[3];
ws4.readyState = 1;
ws4.onopen();
ws4.onclose({ code: 1000 });
out.bare1000Line = term4.lines.find((l) => l.includes('Disconnected — code 1000')) ?? null;

console.log(JSON.stringify(out));
process.exit(0);
