// Runs websocket.js under node with a fake WebSocket and drives the
// connection lifecycle (SHE-66): a disconnect must surface as a gated
// "Reconnecting…" status, repeated failures escalate to "unreachable", and a
// successful REconnect (not the first connect) restores the status and
// dispatches shelves:ws-reconnected so subscribers resync tree + preview.
//
// Usage: node run_ws_status.mjs
// Prints one JSON object of observations (asserted by
// tests/test_studio_ws_status.py).

// Clamp timers so the 1s down-gate and 2s reconnect backoff run in ~50ms.
// Ordering within a step doesn't matter — the harness awaits between steps.
const realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms, ...args) =>
  realSetTimeout(fn, Math.min(ms ?? 0, 50), ...args);

const sleep = (ms) => new Promise((r) => realSetTimeout(r, ms));

// ── DOM / env stubs ──
const els = new Map();
function stubEl(id) {
  if (!els.has(id)) els.set(id, { id, className: '', textContent: '' });
  return els.get(id);
}

const listeners = new Map();
globalThis.document = {
  querySelector: (sel) => stubEl(sel),
  addEventListener(type, fn) {
    if (!listeners.has(type)) listeners.set(type, []);
    listeners.get(type).push(fn);
  },
  dispatchEvent(ev) {
    for (const fn of listeners.get(ev.type) ?? []) fn(ev);
  },
};

globalThis.CustomEvent = class CustomEvent {
  constructor(type, opts) {
    this.type = type;
    this.detail = opts?.detail;
  }
};

globalThis.location = { protocol: 'http:', host: '127.0.0.1:8089' };

const sockets = [];
globalThis.WebSocket = class FakeWebSocket {
  constructor(url) {
    this.url = url;
    sockets.push(this);
  }
};

const { state } = await import('../../shelves/studio/static/js/state.js');
const { connectWebSocket } = await import('../../shelves/studio/static/js/websocket.js');

let resyncCount = 0;
document.addEventListener('shelves:ws-reconnected', () => { resyncCount += 1; });

const dot = stubEl('#statusbar .sh-status-dot');
const msg = stubEl('#statusbar .sh-status-msg');
const out = {};

// ── First connect: no resync, status connected ──
connectWebSocket();
sockets.at(-1).onopen();
out.initialStatus = state.wsStatus;
out.initialResyncCount = resyncCount;

// ── Disconnect: status change is gated, then paints ──
sockets.at(-1).onclose();
out.statusRightAfterClose = state.wsStatus;  // still 'connected' inside the gate
await sleep(120);                            // past clamped gate + reconnect backoff
out.statusAfterGate = state.wsStatus;
out.dotAfterGate = dot.className;
out.msgAfterGate = msg.textContent;

// ── Reconnect succeeds: status restored, resync dispatched once ──
sockets.at(-1).onopen();
out.statusAfterReconnect = state.wsStatus;
out.resyncAfterReconnect = resyncCount;

// ── Server stays down: repeated failures escalate ──
for (let i = 0; i < 6; i++) {
  sockets.at(-1).onclose();
  await sleep(80);  // let the scheduled reconnect create the next socket
}
out.statusAfterManyFailures = state.wsStatus;
out.msgAfterManyFailures = msg.textContent;

// ── Coming back after unreachable still recovers + resyncs ──
sockets.at(-1).onopen();
out.statusAfterRecovery = state.wsStatus;
out.resyncAfterRecovery = resyncCount;

console.log(JSON.stringify(out));
process.exit(0);  // pending reconnect timers must not delay exit
