// ─── WebSocket Manager ─────────────────────────────────────
// Single connection, dispatches typed DOM events.
// No monkey-patching — each module subscribes independently.

import { WS_RECONNECT_MS } from './state.js';

let ws = null;

export function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

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
    setTimeout(connectWebSocket, WS_RECONNECT_MS);
  };

  ws.onerror = (e) => {
    console.warn('[shelves] WS error:', e);
  };
}
