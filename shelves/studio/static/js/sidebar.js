// ─── Sidebar Module ────────────────────────────────────────
// File explorer tree, sidebar toggle, active file highlighting, and file
// management (SHE-42): create / rename / duplicate / delete.

import { state, updateBreadcrumb, updateStatusBar } from './state.js';
import { renameNavEntries } from './nav.js';

const STORAGE_KEY_COLLAPSED   = 'shelves-studio-collapsed-dirs';
const STORAGE_KEY_SIDEBAR_VIS = 'shelves-studio-sidebar-visible';
const STORAGE_KEY_SIDEBAR_W   = 'shelves-studio-sidebar-width';

const SIDEBAR_DEFAULT_W = 220;  // studio.css .sh-main tree column
const SIDEBAR_MIN_W = 140;
const SIDEBAR_RAIL_W = 36;      // collapsed rail strip (SHE-41)

let treeData = [];
let collapsedDirs = new Set(
  JSON.parse(localStorage.getItem(STORAGE_KEY_COLLAPSED) || '[]')
);
let sidebarVisible = localStorage.getItem(STORAGE_KEY_SIDEBAR_VIS) !== 'false';

// ─── File-Type Icons ───────────────────────────────────────
// Lucide icons, inlined (no runtime dep — we use 6 glyphs). 1.5px stroke,
// currentColor, 24-grid rendered at 14px. Transcribed from lucide.dev.
const ICON_ATTRS = 'xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"';

const ICONS = {
  folder:    `<svg ${ICON_ATTRS}><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>`,
  chart:     `<svg ${ICON_ATTRS}><path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg>`,                        // bar-chart-3
  dashboard: `<svg ${ICON_ATTRS}><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="12" rx="1"/></svg>`,          // layout-dashboard
  model:     `<svg ${ICON_ATTRS}><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/></svg>`, // database
  json:      `<svg ${ICON_ATTRS}><path d="M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5c0 1.1.9 2 2 2h1"/><path d="M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"/></svg>`,                                   // braces
  file:      `<svg ${ICON_ATTRS}><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>`,                                    // file-text
  plus:      `<svg ${ICON_ATTRS}><path d="M5 12h14"/><path d="M12 5v14"/></svg>`,
  theme:     `<svg ${ICON_ATTRS}><circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/></svg>`, // palette
};

function iconForEntry(entry, groupRole) {
  // /project ships typed top-level groups (SHE-39); files inherit their
  // group's role regardless of what the configured dir is named.
  if (entry.type === 'dir') return ICONS.folder;
  if (groupRole === 'charts')     return ICONS.chart;
  if (groupRole === 'dashboards') return ICONS.dashboard;
  if (groupRole === 'models')     return ICONS.model;
  if (groupRole === 'theme')      return ICONS.theme;
  if (entry.path.endsWith('.json')) return ICONS.json;
  return ICONS.file;
}

// ─── Fetch Tree ────────────────────────────────────────────
async function fetchTree() {
  try {
    const resp = await fetch('/project');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    treeData = await resp.json();
    renderTree();
  } catch (e) {
    const ft = document.getElementById('file-tree');
    ft.innerHTML = '<div class="tree-placeholder">Error loading project</div>';
    console.error('[shelves] fetchTree error:', e);
  }
}

// ─── File Ops (SHE-42) ─────────────────────────────────────

function defaultExt(name) {
  // 'weekly' → 'weekly.yaml'; anything already containing a dot is untouched
  return name.includes('.') ? name : name + '.yaml';
}

async function createFile(dirPath, name, content = null) {
  const path = `${dirPath}/${defaultExt(name.trim())}`;
  const opts = { method: 'POST' };
  if (content != null) opts.body = content;
  const resp = await fetch(`/file?path=${encodeURIComponent(path)}`, opts);
  const text = resp.ok ? '' : await resp.text().catch(() => '');
  return { ok: resp.ok, status: resp.status, path, text };
}

async function renameFile(oldPath, newName) {
  const dir = oldPath.split('/').slice(0, -1).join('/');
  const to = `${dir}/${defaultExt(newName.trim())}`;
  if (to === oldPath) return { ok: true, path: to };
  const resp = await fetch(
    `/file/rename?path=${encodeURIComponent(oldPath)}&to=${encodeURIComponent(to)}`,
    { method: 'POST' },
  );
  // Any successful rename remaps history (SHE-40) — a non-open file can be
  // in the nav stack too, and a stale entry would be pruned as not-found.
  if (resp.ok) renameNavEntries(oldPath, to);
  if (resp.ok && state.currentFile?.path === oldPath) {
    // Renaming the open file must never drop the buffer (dirty or not):
    // update the path in place. The rename's own deleted(old) broadcast may
    // have raced in and flagged the file as deleted — clear that now.
    state.currentFile.path = to;
    state.fileDeleted = false;
    updateBreadcrumb(to, state.currentFile.dirty);
    updateStatusBar();
  }
  const text = resp.ok ? '' : await resp.text().catch(() => '');
  return { ok: resp.ok, status: resp.status, path: to, text };
}

async function deleteFileOp(path) {
  const resp = await fetch(`/file?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
  if (!resp.ok) {
    const text = (await resp.text().catch(() => '')) || `HTTP ${resp.status}`;
    alert(`Could not delete file: ${text}`);
  }
  // Deleting the OPEN file needs no special casing here: the server's
  // file_change broadcast drives editor.js's SHE-51 deleted-on-disk notice,
  // and the buffer is deliberately kept (it may be the only surviving copy).
  fetchTree();
}

function siblingNames(path) {
  // Names in the same tree-data children list as `path`.
  function walk(entries) {
    for (const entry of entries) {
      if (entry.path === path) return entries.map(e => e.name);
      if (entry.children) {
        const found = walk(entry.children);
        if (found) return found;
      }
    }
    return null;
  }
  return walk(treeData) ?? [];
}

async function duplicateFile(path) {
  const resp = await fetch(`/file?path=${encodeURIComponent(path)}`);
  if (!resp.ok) {
    alert(`Could not read file to duplicate: HTTP ${resp.status}`);
    return;
  }
  const { content } = await resp.json();
  const dir = path.split('/').slice(0, -1).join('/');
  const name = path.split('/').pop();
  const dot = name.lastIndexOf('.');
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const ext = dot > 0 ? name.slice(dot) : '';
  const siblings = new Set(siblingNames(path));
  let copy = `${stem}-copy${ext}`;
  for (let n = 2; siblings.has(copy); n++) copy = `${stem}-copy-${n}${ext}`;
  const r = await createFile(dir, copy, content);
  if (!r.ok) alert(`Could not duplicate file: ${r.text || `HTTP ${r.status}`}`);
  fetchTree();   // no auto-open — matches VS Code duplicate behavior
}

// ─── Context Menu (SHE-42) ─────────────────────────────────
// Singleton on document.body, styled per docs/design-system/components-nav.html.
let menuEl = null;
let menuCleanup = null;

function closeTreeMenu() {
  if (!menuEl) return;
  menuEl.remove();
  menuEl = null;
  if (menuCleanup) { menuCleanup(); menuCleanup = null; }
}

// items: array of {label, danger?, confirm?, onClick} or 'sep'. A confirm
// item is two-step: the first click re-labels it 'Confirm delete?' in place
// (in-place affordance, no modal); only the second click executes.
function showTreeMenu(x, y, items) {
  closeTreeMenu();
  const menu = document.createElement('div');
  // .sh-menu carries the DS look (SHE-36 atoms); .tree-menu adds positioning.
  menu.className = 'sh-menu tree-menu';
  for (const it of items) {
    if (it === 'sep') {
      const sep = document.createElement('div');
      sep.className = 'sh-menu-sep';
      menu.appendChild(sep);
      continue;
    }
    const item = document.createElement('div');
    item.className = 'sh-menu-item' + (it.danger ? ' is-danger' : '');
    item.textContent = it.label;   // our own constants, but keep the textContent rule
    item.addEventListener('click', (e) => {
      if (it.confirm && item.dataset.armed !== '1') {
        item.dataset.armed = '1';
        item.textContent = 'Confirm delete?';
        e.stopPropagation();       // keep the menu open for the second click
        return;
      }
      it.onClick();
      closeTreeMenu();
    });
    menu.appendChild(item);
  }
  document.body.appendChild(menu);
  // Clamp into the viewport after measuring.
  const rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(0, Math.min(x, window.innerWidth - rect.width - 4)) + 'px';
  menu.style.top = Math.max(0, Math.min(y, window.innerHeight - rect.height - 4)) + 'px';

  const dismiss = () => closeTreeMenu();
  const onKey = (e) => { if (e.key === 'Escape') closeTreeMenu(); };
  document.addEventListener('click', dismiss);
  document.addEventListener('contextmenu', dismiss);
  document.addEventListener('keydown', onKey);
  document.addEventListener('scroll', dismiss, true);
  window.addEventListener('resize', dismiss);
  menuCleanup = () => {
    document.removeEventListener('click', dismiss);
    document.removeEventListener('contextmenu', dismiss);
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('scroll', dismiss, true);
    window.removeEventListener('resize', dismiss);
  };
  menuEl = menu;
}

// ─── Inline Inputs (SHE-42) ────────────────────────────────
let activeInputRow = null;

function removeActiveInput() {
  if (!activeInputRow) return;
  activeInputRow.remove();
  activeInputRow = null;
}

function startCreateInput(dirPath, depth, afterRow) {
  removeActiveInput();
  const row = document.createElement('div');
  row.className = 'tree-file tree-input';
  row.style.paddingLeft = (14 + (depth + 1) * 12) + 'px';

  const input = document.createElement('input');
  input.placeholder = 'name.yaml';
  input.addEventListener('click', (e) => e.stopPropagation());
  input.addEventListener('input', () => input.classList.remove('is-error'));
  let done = false;
  input.addEventListener('keydown', async (e) => {
    if (e.key === 'Escape') { done = true; removeActiveInput(); return; }
    if (e.key !== 'Enter' || done) return;
    const name = input.value.trim();
    if (!name) { done = true; removeActiveInput(); return; }
    const r = await createFile(dirPath, name);
    if (r.status === 409) {
      input.classList.add('is-error');
      input.title = 'File already exists';
      return;                       // stay in the input; typing clears the error
    }
    if (!r.ok) {
      alert(`Could not create file: ${r.text || `HTTP ${r.status}`}`);
      done = true;
      removeActiveInput();
      return;
    }
    done = true;
    removeActiveInput();
    await fetchTree();
    window.shelvesStudio?.openFile(r.path);
  });
  input.addEventListener('blur', () => { if (!done) removeActiveInput(); });

  row.appendChild(input);
  afterRow.parentNode.insertBefore(row, afterRow.nextSibling);
  activeInputRow = row;
  input.focus();
}

function startRenameInput(row, entry) {
  const nameSpan = row.querySelector('.tree-name');
  if (!nameSpan || row.querySelector('input')) return;
  const input = document.createElement('input');
  input.value = entry.name;
  input.addEventListener('click', (e) => e.stopPropagation());
  input.addEventListener('input', () => input.classList.remove('is-error'));
  let done = false;
  const restore = () => { input.remove(); nameSpan.style.display = ''; };
  input.addEventListener('keydown', async (e) => {
    if (e.key === 'Escape') { done = true; restore(); return; }
    if (e.key !== 'Enter' || done) return;
    const newName = input.value.trim();
    if (!newName || newName === entry.name) { done = true; restore(); return; }
    const r = await renameFile(entry.path, newName);
    if (!r.ok) {
      input.classList.add('is-error');
      input.title = r.text || `HTTP ${r.status}`;
      return;
    }
    done = true;
    fetchTree();   // the re-render restores the row; highlight follows currentFile
  });
  input.addEventListener('blur', () => { if (!done) restore(); });
  row.classList.add('tree-input');
  nameSpan.style.display = 'none';
  row.appendChild(input);
  input.focus();
  input.select();
}

// ─── Render Tree ───────────────────────────────────────────
function renderTree() {
  const ft = document.getElementById('file-tree');
  ft.innerHTML = '';
  if (!treeData || treeData.length === 0) {
    ft.innerHTML = '<div class="tree-placeholder">No files</div>';
    return;
  }
  ft.appendChild(renderTreeLevel(treeData, 0));
  highlightActiveFile();
}

function renderTreeLevel(entries, depth, groupRole) {
  const container = document.createElement('div');
  for (const entry of entries) {
    // Top-level entries carry the group role; descendants inherit it.
    const role = entry.group ?? groupRole;
    const row = document.createElement('div');
    row.style.paddingLeft = (14 + depth * 12) + 'px';

    if (entry.type === 'dir') {
      row.className = 'tree-dir';
      row.dataset.path = entry.path;

      const chevron = document.createElement('span');
      chevron.className = 'tree-chevron';
      const collapsed = collapsedDirs.has(entry.path);
      chevron.innerHTML = collapsed
        ? '<svg width="10" height="10" viewBox="0 0 10 10"><path d="M3 1.5L7 5L3 8.5" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        : '<svg width="10" height="10" viewBox="0 0 10 10"><path d="M1.5 3L5 7L8.5 3" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';

      const name = document.createElement('span');
      name.className = 'tree-name';
      name.textContent = entry.name;

      row.appendChild(chevron);
      row.appendChild(name);

      // Group headers get the "new file" affordance (SHE-42); assets keeps
      // no create affordance, mirroring the backend's omit-when-empty rule.
      if (depth === 0 && entry.group && entry.group !== 'assets') {
        const add = document.createElement('button');
        add.className = 'tree-add';
        add.title = 'New file';
        add.innerHTML = ICONS.plus;
        add.addEventListener('click', (e) => {
          e.stopPropagation();     // don't toggle the dir
          startCreateInput(entry.path, depth, row);
        });
        row.appendChild(add);
      }

      row.addEventListener('click', () => toggleDir(entry.path));
      row.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();       // the document-level dismiss listener must not eat this menu
        showTreeMenu(e.clientX, e.clientY, [
          { label: 'New file', onClick: () => startCreateInput(entry.path, depth, row) },
        ]);
      });
      container.appendChild(row);

      if (!collapsedDirs.has(entry.path) && entry.children?.length) {
        container.appendChild(renderTreeLevel(entry.children, depth + 1, role));
      }
    } else {
      row.className = 'tree-file';
      row.dataset.path = entry.path;

      // Icons are our own constant strings; names are filesystem input and
      // must keep going through textContent, never innerHTML.
      const icon = document.createElement('span');
      icon.className = 'tree-icon';
      icon.innerHTML = iconForEntry(entry, role);

      const name = document.createElement('span');
      name.className = 'tree-name';
      name.textContent = entry.name;
      name.title = entry.name;              // long names truncate; tooltip for free

      row.appendChild(icon);
      row.appendChild(name);
      row.addEventListener('click', () => window.shelvesStudio.openFile(entry.path));
      // The theme entry is open-only (SHE-44): renaming/deleting/duplicating
      // it would break the --theme path the server resolved at startup.
      if (role !== 'theme') {
        row.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          e.stopPropagation();
          const dirPath = entry.path.split('/').slice(0, -1).join('/');
          showTreeMenu(e.clientX, e.clientY, [
            // depth-1: the input lands at the file's own indent, inside its dir
            { label: 'New file', onClick: () => startCreateInput(dirPath, depth - 1, row) },
            { label: 'Rename', onClick: () => startRenameInput(row, entry) },
            { label: 'Duplicate', onClick: () => duplicateFile(entry.path) },
            'sep',
            { label: 'Delete', danger: true, confirm: true, onClick: () => deleteFileOp(entry.path) },
          ]);
        });
      }
      container.appendChild(row);
    }
  }
  return container;
}

// ─── Active File Highlighting ──────────────────────────────
function highlightActiveFile() {
  document.querySelectorAll('.tree-file').forEach(el => el.classList.remove('active'));
  if (state.currentFile) {
    const active = document.querySelector(`.tree-file[data-path="${CSS.escape(state.currentFile.path)}"]`);
    if (active) active.classList.add('active');
  }
}

// ─── Directory Collapse/Expand ─────────────────────────────
function toggleDir(path) {
  if (collapsedDirs.has(path)) {
    collapsedDirs.delete(path);
  } else {
    collapsedDirs.add(path);
  }
  localStorage.setItem(STORAGE_KEY_COLLAPSED, JSON.stringify([...collapsedDirs]));
  renderTree();
}

// ─── Sidebar Resize ────────────────────────────────────────
function clampSidebarWidth(px) {
  return Math.max(SIDEBAR_MIN_W, Math.min(window.innerWidth * 0.5, px));
}

function setSidebarWidth(px) {
  document.documentElement.style.setProperty('--sidebar-width', px + 'px');
}

function storedSidebarWidth() {
  const v = parseFloat(localStorage.getItem(STORAGE_KEY_SIDEBAR_W));
  // Clamp at read time only — persisting the clamp would let a narrow
  // window permanently shrink the stored preference.
  return Number.isFinite(v) ? clampSidebarWidth(v) : SIDEBAR_DEFAULT_W;
}

function applySidebarVisibility() {
  const sidebar = document.getElementById('sidebar');
  const handle = document.getElementById('sidebar-resize-handle');
  if (sidebarVisible) {
    sidebar.classList.remove('collapsed');
    setSidebarWidth(storedSidebarWidth());
    document.documentElement.style.setProperty('--sidebar-handle-w', '1px');
    handle.classList.remove('hidden');
  } else {
    sidebar.classList.add('collapsed');
    // Narrow to the rail strip + zero the handle track; the stored width
    // survives for reopen (SHE-41).
    document.documentElement.style.setProperty('--sidebar-width', SIDEBAR_RAIL_W + 'px');
    document.documentElement.style.setProperty('--sidebar-handle-w', '0px');
    handle.classList.add('hidden');
  }
}

function initSidebarResize() {
  const handle = document.getElementById('sidebar-resize-handle');
  const sidebar = document.getElementById('sidebar');
  let dragging = false;

  handle.addEventListener('pointerdown', (e) => {
    dragging = true;
    handle.classList.add('dragging');
    handle.setPointerCapture(e.pointerId);   // survives fast drags + the dashboard iframe
    e.preventDefault();                       // no text selection while dragging
  });
  handle.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const left = sidebar.getBoundingClientRect().left;
    setSidebarWidth(clampSidebarWidth(e.clientX - left));
  });
  // pointerup is not the only way a drag ends: touch scrolling, OS gestures,
  // or losing capture fire pointercancel/lostpointercapture instead, and the
  // drag must terminate on those too or the handle sticks in dragging mode.
  function endDrag(e) {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    try { handle.releasePointerCapture(e.pointerId); } catch (_) {}  // capture may already be gone
    const w = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-width'));
    if (Number.isFinite(w)) localStorage.setItem(STORAGE_KEY_SIDEBAR_W, String(Math.round(w)));
  }
  handle.addEventListener('pointerup', endDrag);
  handle.addEventListener('pointercancel', endDrag);
  handle.addEventListener('lostpointercapture', endDrag);
  handle.addEventListener('dblclick', () => {
    setSidebarWidth(SIDEBAR_DEFAULT_W);
    localStorage.setItem(STORAGE_KEY_SIDEBAR_W, String(SIDEBAR_DEFAULT_W));
  });
}

// ─── Sidebar Toggle ────────────────────────────────────────
// Arm the workspace slide for this toggle only (drag-resize must stay 1:1).
function animateWorkspaceOnce() {
  const ws = document.getElementById('workspace');
  ws.classList.add('animating');
  function clear(e) {
    // transitionend BUBBLES: a 140ms hover/active transition ending on any
    // descendant (buttons, tree rows) would kill the 240ms slide mid-flight.
    // Only the workspace's own grid transition — or the no-arg fallback
    // timer — may clear the class.
    if (e && (e.target !== ws || e.propertyName !== 'grid-template-columns')) return;
    ws.classList.remove('animating');
    ws.removeEventListener('transitionend', clear);
  }
  ws.addEventListener('transitionend', clear);
  setTimeout(clear, 400);   // fallback: browsers that can't animate grid tracks never fire the event
}

export function toggleSidebar() {
  sidebarVisible = !sidebarVisible;
  animateWorkspaceOnce();
  applySidebarVisibility();
  localStorage.setItem(STORAGE_KEY_SIDEBAR_VIS, String(sidebarVisible));
}

// ─── Init ──────────────────────────────────────────────────
export function initSidebar() {
  applySidebarVisibility();
  initSidebarResize();

  document.getElementById('sidebar-toggle-inner').addEventListener('click', toggleSidebar);
  document.getElementById('sidebar-rail')?.addEventListener('click', toggleSidebar);

  let treeRefreshTimer = null;
  document.addEventListener('shelves:file-change', () => {
    clearTimeout(treeRefreshTimer);
    treeRefreshTimer = setTimeout(fetchTree, 500);
  });

  document.addEventListener('shelves:active-file-changed', () => highlightActiveFile());

  // The server restarted while we were disconnected — files may have changed
  // without any file_change broadcast reaching us (SHE-66).
  document.addEventListener('shelves:ws-reconnected', () => fetchTree());

  fetchTree();
}
