// ─── WebSocket Manager ─────────────────────────────────────
// Single connection, dispatches typed DOM events.
// No monkey-patching — each module subscribes independently.

import {
  state, WS_RECONNECT_MS, WS_DOWN_GATE_MS, WS_UNREACHABLE_AFTER, updateStatusBar,
} from './state.js';

let ws = null;
let hadConnection = false;  // an onopen has fired at least once this session
let wasDown = false;        // a close happened since the last open
let failedRetries = 0;
let downGateTimer = null;

function setWsStatus(status) {
  if (state.wsStatus === status) return;
  state.wsStatus = status;
  updateStatusBar();
}

export function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    clearTimeout(downGateTimer);
    downGateTimer = null;
    failedRetries = 0;
    const reconnected = hadConnection && wasDown;
    hadConnection = true;
    wasDown = false;
    setWsStatus('connected');
    if (reconnected) {
      // The server restarted (or came back): the tree and the last compile
      // may be stale — subscribers re-fetch the tree and recompile (SHE-66).
      document.dispatchEvent(new CustomEvent('shelves:ws-reconnected'));
    }
  };

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    // No status-bar calls here: the editor.js / dashboard.js event handlers
    // own the status bar, and they path-guard foreign broadcasts (SHE-49/50).
    switch (msg.type) {
      case 'compile_result':
        document.dispatchEvent(new CustomEvent('shelves:compile-result', { detail: msg }));
        break;

      case 'file_change':
        document.dispatchEvent(new CustomEvent('shelves:file-change', { detail: msg }));
        break;

      case 'dashboard_compile_result':
        document.dispatchEvent(new CustomEvent('shelves:dashboard-result', { detail: msg }));
        break;
    }
  };

  ws.onclose = () => {
    ws = null;
    wasDown = true;
    failedRetries += 1;
    if (failedRetries >= WS_UNREACHABLE_AFTER) {
      clearTimeout(downGateTimer);
      downGateTimer = null;
      setWsStatus('unreachable');
    } else if (state.wsStatus === 'connected' && downGateTimer === null) {
      // Gate the first paint so a sub-second blip (uvicorn --reload) doesn't
      // flash "Reconnecting…" for every save.
      downGateTimer = setTimeout(() => {
        downGateTimer = null;
        setWsStatus('reconnecting');
      }, WS_DOWN_GATE_MS);
    }
    setTimeout(connectWebSocket, WS_RECONNECT_MS);
  };

  ws.onerror = (e) => {
    console.warn('[shelves] WS error:', e);
  };
}
