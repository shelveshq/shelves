// ─── Terminal Module ───────────────────────────────────────
// Integrated terminal panel with xterm.js and PTY backend.
//
// Open path (SHE-47): the panel is shown and sized FIRST, then the terminal
// is created, opened and fitted synchronously — the WebSocket connects after.
// The old order gated term.open() on ws.onopen, so any connection/auth
// failure left a blank box with its error written into a never-opened
// terminal. Every failure path now renders into a visible terminal (or a
// plain error card when xterm itself failed to load).

const STORAGE_KEY_TERM_HEIGHT = 'shelves-studio-terminal-height';

// Overridable so the node test harness can substitute a local fake module
// (node cannot import https: URLs). Production always uses the CDN defaults.
const XTERM_SRC =
  globalThis.__shelvesXtermSrc ?? 'https://cdn.jsdelivr.net/npm/@xterm/xterm@5/+esm';
const XTERM_FIT_SRC =
  globalThis.__shelvesXtermFitSrc ?? 'https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0/+esm';

// xterm renders to canvas and can't read CSS vars — resolved hex values,
// mirroring the DS tokens (docs/design-system/studio/tokens.css --term-*
// plus an ANSI 16 palette tuned to the editorial hues).
const XTERM_THEME = {
  background: '#0B0B0A',          // --ink-12 / --term-bg
  foreground: '#E8E4D8',          // --paper-edge / --term-fg
  cursor: '#B8531C',              // --brand-ochre
  cursorAccent: '#0B0B0A',
  selectionBackground: '#F7E9DC', // --brand-ochre-tint
  selectionForeground: '#0B0B0A',
  black: '#1A1916',               // --ink-10
  red: '#C96A54',
  green: '#9DD6B1',               // --term-prompt
  yellow: '#D2A63C',
  blue: '#9DB7D6',                // --term-dir
  magenta: '#C39BC7',
  cyan: '#8FC8C2',
  white: '#E8E4D8',               // --paper-edge
  brightBlack: '#9A968B',         // --ink-4
  brightRed: '#E08573',
  brightGreen: '#B8E4C9',
  brightYellow: '#E5C063',
  brightBlue: '#B8CDE6',
  brightMagenta: '#DAB8DD',
  brightCyan: '#ABDCD6',
  brightWhite: '#FAF8F3',         // --paper
};

let terminals = [];
let activeTerminalId = null;
let terminalPanelHeight = parseInt(localStorage.getItem(STORAGE_KEY_TERM_HEIGHT) || '250');
let terminalPanelVisible = false;
let _termIdCounter = 0;

let Terminal = null;
let FitAddon = null;
let xtermLoadFailed = false;

function getTerminalToken() {
  const meta = document.querySelector('meta[name="shelves-terminal-token"]');
  return meta?.content || '';
}

// ─── Create Terminal Tab ─────────────────────────────────
function createTerminal() {
  if (!Terminal || !FitAddon) {
    showLibraryError();
    return;
  }
  const id = ++_termIdCounter;
  const name = `Terminal ${id}`;

  const term = new Terminal({
    fontFamily: '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace',
    fontSize: 12,
    lineHeight: 1.4,
    theme: XTERM_THEME,
    cursorBlink: true,
    scrollback: 5000,
  });
  const fitAddon = new FitAddon();
  term.loadAddon(fitAddon);

  const container = document.createElement('div');
  container.dataset.termId = id;
  // inset (not padding): xterm fills the element, so breathing room comes
  // from offsetting it inside the relatively-positioned #terminal-container.
  container.style.cssText = 'display:none; position:absolute; inset:8px 0 8px 12px;';
  document.getElementById('terminal-container').appendChild(container);

  const entry = { id, term, fitAddon, ws: null, name, container, ro: null, userClosed: false };
  terminals.push(entry);

  const tabEl = document.createElement('div');
  tabEl.className = 'terminal-tab';
  tabEl.dataset.termId = id;
  tabEl.innerHTML = `<span>${name}</span><span class="terminal-tab-close" title="Close">&times;</span>`;
  tabEl.addEventListener('click', (e) => {
    if (e.target.classList?.contains('terminal-tab-close')) {
      closeTerminal(id);
    } else {
      switchTerminal(id);
    }
  });
  document.getElementById('terminal-tabs').appendChild(tabEl);

  // Open + fit synchronously — the panel is already visible and sized, so
  // the terminal renders immediately and every later failure is readable.
  switchTerminal(id);
  term.open(container);
  fitAddon.fit();

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const termWs = new WebSocket(`${proto}://${location.host}/ws/terminal`);
  entry.ws = termWs;

  termWs.onopen = () => {
    termWs.send(JSON.stringify({ type: 'auth', token: getTerminalToken() }));
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
      dimTab(id);
    }
  };

  termWs.onerror = () => {
    term.writeln('\r\n\x1b[31m[Connection error]\x1b[0m');
  };

  // The server's auth/origin-reject path closes with 1008 — that fires
  // onclose, not onerror, so without this handler a token failure rendered
  // nothing at all (the strongest "blank panel" path pre-SHE-47).
  termWs.onclose = (event) => {
    if (entry.userClosed) return;
    if (event.code === 1008) {
      term.writeln('\r\n\x1b[31m[Terminal connection rejected (auth)]\x1b[0m');
      term.writeln('\x1b[2mThe terminal token is missing or stale. Reload the page to get a fresh one.\x1b[0m');
    } else if (event.code !== 1000) {
      term.writeln(`\r\n\x1b[2m[Disconnected — code ${event.code}]\x1b[0m`);
    }
    dimTab(id);
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
  entry.ro = ro;
}

function dimTab(id) {
  const tabEl = document.querySelector(`.terminal-tab[data-term-id="${id}"]`);
  if (tabEl) tabEl.classList.add('is-dead');
}

// Visible fallback when the xterm CDN import failed (offline, blocker):
// the panel must still open and say WHY there is no shell.
function showLibraryError() {
  const container = document.getElementById('terminal-container');
  if (container.querySelector('.terminal-lib-error')) return;
  const card = document.createElement('div');
  card.className = 'terminal-lib-error';
  card.textContent = xtermLoadFailed
    ? 'Terminal unavailable — the xterm.js library failed to load (CDN unreachable or blocked). Check your network and reload.'
    : 'Terminal is still loading — try again in a moment.';
  container.appendChild(card);
}

// ─── Switch Terminal Tab ─────────────────────────────────
function switchTerminal(id) {
  terminals.forEach(({ container, id: tid }) => {
    container.style.display = tid === id ? 'block' : 'none';
  });
  document.querySelectorAll('.terminal-tab').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.termId) === id);
  });
  activeTerminalId = id;
  const entry = terminals.find(t => t.id === id);
  // term.element is set by term.open() — during creation switchTerminal runs
  // first (the container must be display:block before opening), so skip the
  // fit for a not-yet-opened terminal; createTerminal fits right after open.
  if (entry && terminalPanelVisible && entry.term.element) entry.fitAddon.fit();
}

// ─── Close Terminal Tab ──────────────────────────────────
function closeTerminal(id) {
  const idx = terminals.findIndex(t => t.id === id);
  if (idx === -1) return;
  const entry = terminals[idx];
  entry.userClosed = true;  // suppress the onclose "[Disconnected]" write
  entry.ro?.disconnect();
  if (entry.ws && entry.ws.readyState === WebSocket.OPEN) entry.ws.close();
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
  // By id, not `.sh-status-term` — other chips may share that class.
  const termBtn = document.getElementById('terminal-toggle-status');
  if (terminalPanelVisible) {
    // Show + size the panel BEFORE creating the first terminal so
    // term.open()/fit() run against a laid-out container.
    panel.classList.remove('collapsed');
    panel.style.height = terminalPanelHeight + 'px';
    if (termBtn) termBtn.classList.add('is-active');
    if (terminals.length === 0) {
      createTerminal();
    } else if (activeTerminalId !== null) {
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
// Pointer-captured on the sidebar-handle recipe (SHE-53/SHE-38) so drags
// survive fast moves, leaving the window, and the dashboard iframe.
function initTerminalResizeHandle() {
  const handle = document.getElementById('terminal-resize-handle');
  const panel = document.getElementById('terminal-panel');
  let dragging = false;
  let startY = 0;
  let startH = 0;

  handle.addEventListener('pointerdown', (e) => {
    dragging = true;
    startY = e.clientY;
    startH = terminalPanelHeight;
    handle.classList.add('dragging');
    panel.classList.add('no-anim');  // the open/close height transition must not lag the drag
    handle.setPointerCapture(e.pointerId);   // survives fast drags + the dashboard iframe
    e.preventDefault();                       // no text selection while dragging
  });

  handle.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const delta = startY - e.clientY;
    terminalPanelHeight = Math.max(80, Math.min(800, startH + delta));
    panel.style.height = terminalPanelHeight + 'px';
  });

  // pointerup is not the only way a drag ends: touch scrolling, OS gestures,
  // or losing capture fire pointercancel/lostpointercapture instead, and the
  // drag must terminate on those too or the handle sticks in dragging mode.
  function endDrag(e) {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    panel.classList.remove('no-anim');
    try { handle.releasePointerCapture(e.pointerId); } catch (_) {}  // capture may already be gone
    localStorage.setItem(STORAGE_KEY_TERM_HEIGHT, String(terminalPanelHeight));
    if (activeTerminalId !== null) {
      const entry = terminals.find(t => t.id === activeTerminalId);
      if (entry) entry.fitAddon.fit();
    }
  }
  handle.addEventListener('pointerup', endDrag);
  handle.addEventListener('pointercancel', endDrag);
  handle.addEventListener('lostpointercapture', endDrag);
}

// ─── Init ──────────────────────────────────────────────────
export async function initTerminal() {
  // Bind the UI BEFORE the CDN import: if xterm never loads, the toggle
  // must still open the panel and show a readable error instead of a
  // dead button (feedback-less open path, SHE-47).
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === '`') {
      e.preventDefault();
      toggleTerminalPanel();
    }
  });
  document.getElementById('terminal-new').addEventListener('click', createTerminal);
  document.getElementById('terminal-toggle').addEventListener('click', toggleTerminalPanel);
  initTerminalResizeHandle();

  try {
    const xtermModule = await import(XTERM_SRC);
    const fitModule = await import(XTERM_FIT_SRC);
    Terminal = xtermModule.Terminal;
    FitAddon = fitModule.FitAddon;
  } catch (e) {
    xtermLoadFailed = true;
    throw e;  // main.js logs it; the panel itself shows the error card
  }
}
