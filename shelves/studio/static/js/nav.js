// ─── File Navigation History (SHE-40) ──────────────────────
// Back/forward across files opened this session. All navigation funnels
// through editor.js::openFile, so the dirty-buffer confirm (SHE-51) and
// deleted-file handling apply unchanged. openFile is INJECTED via initNav
// (not imported) so editor.js → nav.js → state.js stays acyclic and tests
// can script it (tests/support/run_nav_history.mjs).

import { state, NAV_STACK_MAX } from './state.js';

let _openFile = null;   // set by initNav
let _navBusy = false;   // one navigation at a time — rapid keys must not interleave

export function recordNavigation(path) {
  const nav = state.nav;
  if (nav.stack[nav.index] === path) return;      // re-open of current: no-op
  nav.stack = nav.stack.slice(0, nav.index + 1);  // truncate forward branch
  nav.stack.push(path);
  if (nav.stack.length > NAV_STACK_MAX) nav.stack.shift();
  nav.index = nav.stack.length - 1;
  updateNavButtons();
}

export async function navigateBack() {
  if (_navBusy || !_openFile) return;
  _navBusy = true;
  try {
    const nav = state.nav;
    while (nav.index > 0) {
      const candidate = nav.stack[nav.index - 1];
      const status = await _openFile(candidate, { fromHistory: true });
      if (status === 'opened') { nav.index -= 1; break; }
      if (status === 'not-found') {
        // Deleted since it was opened: prune and keep walking. Removing
        // below index shifts the current entry down one.
        nav.stack.splice(nav.index - 1, 1);
        nav.index -= 1;
        continue;
      }
      break;   // 'cancelled' | 'error' | 'no-editor': stay put, keep the entry
    }
  } finally {
    _navBusy = false;
    updateNavButtons();
  }
}

export async function navigateForward() {
  if (_navBusy || !_openFile) return;
  _navBusy = true;
  try {
    const nav = state.nav;
    while (nav.index < nav.stack.length - 1) {
      const candidate = nav.stack[nav.index + 1];
      const status = await _openFile(candidate, { fromHistory: true });
      if (status === 'opened') { nav.index += 1; break; }
      if (status === 'not-found') { nav.stack.splice(nav.index + 1, 1); continue; }
      break;
    }
  } finally {
    _navBusy = false;
    updateNavButtons();
  }
}

export function renameNavEntries(oldPath, newPath) {
  // SHE-42 renames the open file in place; history must follow or the old
  // path would be spuriously pruned as not-found on the next back.
  state.nav.stack = state.nav.stack.map(p => (p === oldPath ? newPath : p));
}

export function updateNavButtons() {
  const back = document.getElementById('nav-back');
  const fwd = document.getElementById('nav-forward');
  if (!back || !fwd) return;   // harness stubs / early boot
  back.disabled = !(state.nav.index > 0);
  fwd.disabled = !(state.nav.index < state.nav.stack.length - 1);
}

export function initNav({ openFile }) {
  _openFile = openFile;
  document.getElementById('nav-back')?.addEventListener('click', () => navigateBack());
  document.getElementById('nav-forward')?.addEventListener('click', () => navigateForward());

  // Cmd/Ctrl+[ / ] — outside Monaco. Inside Monaco the editor.addCommand
  // bindings (editor.js) handle the same chords; they preventDefault, and
  // the defaultPrevented check here is the double-fire guard.
  document.addEventListener('keydown', (e) => {
    if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
    if (e.key !== '[' && e.key !== ']') return;
    if (e.defaultPrevented) return;
    // Same exclusion as the SHE-41 Cmd+B handler: never steal keys from the
    // embedded terminal.
    if (document.getElementById('terminal-panel')?.contains(e.target)) return;
    e.preventDefault();
    if (e.key === '[') navigateBack(); else navigateForward();
  });

  // Mouse back/forward buttons. mouseup is the event browsers tie history
  // navigation to; preventDefault is best-effort.
  document.addEventListener('mouseup', (e) => {
    if (e.button === 3) { e.preventDefault(); navigateBack(); }
    else if (e.button === 4) { e.preventDefault(); navigateForward(); }
  });

  updateNavButtons();
}
