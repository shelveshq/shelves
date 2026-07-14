// Runs websocket.js under node with a fake WebSocket and verifies a
// theme_changed broadcast is routed to the shelves:theme-changed DOM event
// (SHE-44) so main.js can recompile the open buffer with the new theme.
//
// Usage: node run_theme_event.mjs
// Prints one JSON object (asserted by tests/test_studio_theme_event.py).

// ── DOM / env stubs (pattern: run_ws_status.mjs) ──
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

const { connectWebSocket } = await import('../../shelves/studio/static/js/websocket.js');

const out = { eventFired: false, detailPath: null };
document.addEventListener('shelves:theme-changed', (e) => {
  out.eventFired = true;
  out.detailPath = e.detail?.path ?? null;
});

connectWebSocket();
sockets.at(-1).onopen();
sockets.at(-1).onmessage({
  data: JSON.stringify({ type: 'theme_changed', path: '@theme/brand.yaml' }),
});

console.log(JSON.stringify(out));
process.exit(0);
