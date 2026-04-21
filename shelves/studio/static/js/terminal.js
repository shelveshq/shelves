// ─── Terminal Module ───────────────────────────────────────
// Integrated terminal panel with xterm.js and PTY backend.

const STORAGE_KEY_TERM_HEIGHT = 'shelves-studio-terminal-height';

let terminals = [];
let activeTerminalId = null;
let terminalPanelHeight = parseInt(localStorage.getItem(STORAGE_KEY_TERM_HEIGHT) || '250');
let terminalPanelVisible = false;
let _termIdCounter = 0;

let Terminal = null;
let FitAddon = null;

function getTerminalToken() {
  const meta = document.querySelector('meta[name="shelves-terminal-token"]');
  return meta?.content || '';
}

// ─── Create Terminal Tab ─────────────────────────────────
function createTerminal() {
  const id = ++_termIdCounter;
  const name = `Terminal ${id}`;

  const term = new Terminal({
    fontFamily: 'JetBrains Mono, monospace',
    fontSize: 13,
    theme: {
      background: '#1F1E1B',
      foreground: '#E5E3DB',
      cursor: '#D85A30',
      selectionBackground: '#D85A3033',
    },
    cursorBlink: true,
    scrollback: 5000,
  });
  const fitAddon = new FitAddon();
  term.loadAddon(fitAddon);

  const container = document.createElement('div');
  container.dataset.termId = id;
  container.style.cssText = 'display:none; width:100%; height:100%; position:absolute; inset:0;';
  document.getElementById('terminal-container').appendChild(container);

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const termWs = new WebSocket(`${proto}://${location.host}/ws/terminal`);

  termWs.onopen = () => {
    termWs.send(JSON.stringify({ type: 'auth', token: getTerminalToken() }));
    term.open(container);
    fitAddon.fit();
    const { rows, cols } = term;
    termWs.send(JSON.stringify({ type: 'resize', rows, cols }));
  };

  termWs.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    if (msg.type === 'output') {
      const binary = atob(msg.data);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      term.write(bytes);
    } else if (msg.type === 'exit') {
      term.writeln('\r\n\x1b[2m[Process exited]\x1b[0m');
      const tabEl = document.querySelector(`.terminal-tab[data-term-id="${id}"]`);
      if (tabEl) tabEl.style.opacity = '0.5';
    }
  };

  termWs.onerror = () => {
    term.writeln('\r\n\x1b[31m[Connection error]\x1b[0m');
  };

  term.onData((data) => {
    if (termWs.readyState === WebSocket.OPEN) {
      termWs.send(JSON.stringify({ type: 'input', data }));
    }
  });

  const ro = new ResizeObserver(() => {
    if (activeTerminalId === id && terminalPanelVisible) {
      fitAddon.fit();
      if (termWs.readyState === WebSocket.OPEN) {
        const { rows, cols } = term;
        termWs.send(JSON.stringify({ type: 'resize', rows, cols }));
      }
    }
  });
  ro.observe(document.getElementById('terminal-container'));

  const entry = { id, term, fitAddon, ws: termWs, name, container, ro };
  terminals.push(entry);

  const tabEl = document.createElement('div');
  tabEl.className = 'terminal-tab';
  tabEl.dataset.termId = id;
  tabEl.innerHTML = `<span>${name}</span><span style="margin-left:6px;cursor:pointer;opacity:0.6" title="Close">&times;</span>`;
  tabEl.addEventListener('click', (e) => {
    if (e.target.tagName === 'SPAN' && e.target.title === 'Close') {
      closeTerminal(id);
    } else {
      switchTerminal(id);
    }
  });
  document.getElementById('terminal-tabs').appendChild(tabEl);

  switchTerminal(id);
}

// ─── Switch Terminal Tab ─────────────────────────────────
function switchTerminal(id) {
  terminals.forEach(({ container, id: tid }) => {
    container.style.display = tid === id ? 'block' : 'none';
  });
  document.querySelectorAll('.terminal-tab').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.termId) === id);
  });
  const entry = terminals.find(t => t.id === id);
  if (entry) entry.fitAddon.fit();
  activeTerminalId = id;
}

// ─── Close Terminal Tab ──────────────────────────────────
function closeTerminal(id) {
  const idx = terminals.findIndex(t => t.id === id);
  if (idx === -1) return;
  const entry = terminals[idx];
  entry.ro.disconnect();
  if (entry.ws.readyState === WebSocket.OPEN) entry.ws.close();
  entry.term.dispose();
  entry.container.remove();
  terminals.splice(idx, 1);
  document.querySelector(`.terminal-tab[data-term-id="${id}"]`)?.remove();
  if (terminals.length > 0) {
    switchTerminal(terminals[Math.max(0, idx - 1)].id);
  } else {
    activeTerminalId = null;
    toggleTerminalPanel();
  }
}

// ─── Toggle Terminal Panel ────────────────────────────────
export function toggleTerminalPanel() {
  terminalPanelVisible = !terminalPanelVisible;
  const panel = document.getElementById('terminal-panel');
  const termBtn = document.querySelector('#statusbar .sh-status-term');
  if (terminalPanelVisible) {
    if (terminals.length === 0) createTerminal();
    panel.classList.remove('collapsed');
    panel.style.height = terminalPanelHeight + 'px';
    if (termBtn) termBtn.classList.add('is-active');
    if (activeTerminalId !== null) {
      const entry = terminals.find(t => t.id === activeTerminalId);
      if (entry) entry.fitAddon.fit();
    }
  } else {
    panel.classList.add('collapsed');
    panel.style.height = '';
    if (termBtn) termBtn.classList.remove('is-active');
  }
}

// ─── Terminal Resize Handle ─────────────────────────────
function initTerminalResizeHandle() {
  const handle = document.getElementById('terminal-resize-handle');
  let dragging = false;
  let startY = 0;
  let startH = 0;

  handle.addEventListener('mousedown', (e) => {
    dragging = true;
    startY = e.clientY;
    startH = terminalPanelHeight;
    handle.classList.add('dragging');
    e.preventDefault();
  });

  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const delta = startY - e.clientY;
    terminalPanelHeight = Math.max(80, Math.min(800, startH + delta));
    document.getElementById('terminal-panel').style.height = terminalPanelHeight + 'px';
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    localStorage.setItem(STORAGE_KEY_TERM_HEIGHT, String(terminalPanelHeight));
    if (activeTerminalId !== null) {
      const entry = terminals.find(t => t.id === activeTerminalId);
      if (entry) entry.fitAddon.fit();
    }
  });
}

// ─── Init ──────────────────────────────────────────────────
export async function initTerminal() {
  const xtermModule = await import('https://cdn.jsdelivr.net/npm/@xterm/xterm@5/+esm');
  const fitModule = await import('https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0/+esm');
  Terminal = xtermModule.Terminal;
  FitAddon = fitModule.FitAddon;

  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === '`') {
      e.preventDefault();
      toggleTerminalPanel();
    }
  });

  document.getElementById('terminal-new').addEventListener('click', createTerminal);
  document.getElementById('terminal-toggle').addEventListener('click', toggleTerminalPanel);

  initTerminalResizeHandle();
}
