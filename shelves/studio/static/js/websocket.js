// ─── WebSocket Manager ─────────────────────────────────────
// Single connection, dispatches typed DOM events.
// No monkey-patching — each module subscribes independently.

import { WS_RECONNECT_MS, updateStatusBadge } from './state.js';

let ws = null;

export function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    switch (msg.type) {
      case 'compile_result':
        document.dispatchEvent(new CustomEvent('shelves:compile-result', { detail: msg }));
        updateStatusBadge(msg.errors ?? [], msg.warnings ?? []);
        break;

      case 'file_change':
        document.dispatchEvent(new CustomEvent('shelves:file-change', { detail: msg }));
        break;

      case 'dashboard_compile_result':
        document.dispatchEvent(new CustomEvent('shelves:dashboard-result', { detail: msg }));
        updateStatusBadge(msg.errors ?? [], msg.warnings ?? []);
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
