// ─── Sidebar Module ────────────────────────────────────────
// File explorer tree, sidebar toggle, active file highlighting.

import { state } from './state.js';

const STORAGE_KEY_COLLAPSED   = 'shelves-studio-collapsed-dirs';
const STORAGE_KEY_SIDEBAR_VIS = 'shelves-studio-sidebar-visible';
const STORAGE_KEY_SIDEBAR_W   = 'shelves-studio-sidebar-width';

const SIDEBAR_DEFAULT_W = 200;
const SIDEBAR_MIN_W = 140;

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
};

function iconForEntry(entry) {
  // Route by top-level group first. Until SHE-39 lands the tree is the raw
  // project walk, so the first path segment is the best signal we have; the
  // names below are the *default* configured dirs.
  // TODO(SHE-39): switch to entry group type once /project ships typed groups.
  if (entry.type === 'dir') return ICONS.folder;
  const top = entry.path.split('/')[0];
  if (top === 'charts')     return ICONS.chart;
  if (top === 'dashboards') return ICONS.dashboard;
  if (top === 'models')     return ICONS.model;
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

function renderTreeLevel(entries, depth) {
  const container = document.createElement('div');
  for (const entry of entries) {
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
      row.addEventListener('click', () => toggleDir(entry.path));
      container.appendChild(row);

      if (!collapsedDirs.has(entry.path) && entry.children?.length) {
        container.appendChild(renderTreeLevel(entry.children, depth + 1));
      }
    } else {
      row.className = 'tree-file';
      row.dataset.path = entry.path;

      // Icons are our own constant strings; names are filesystem input and
      // must keep going through textContent, never innerHTML.
      const icon = document.createElement('span');
      icon.className = 'tree-icon';
      icon.innerHTML = iconForEntry(entry);

      const name = document.createElement('span');
      name.className = 'tree-name';
      name.textContent = entry.name;
      name.title = entry.name;              // long names truncate; tooltip for free

      row.appendChild(icon);
      row.appendChild(name);
      row.addEventListener('click', () => window.shelvesStudio.openFile(entry.path));
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
    // Zero the width + handle track; the stored width survives for reopen.
    document.documentElement.style.setProperty('--sidebar-width', '0px');
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
  handle.addEventListener('pointerup', (e) => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    handle.releasePointerCapture(e.pointerId);
    const w = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-width'));
    if (Number.isFinite(w)) localStorage.setItem(STORAGE_KEY_SIDEBAR_W, String(Math.round(w)));
  });
  handle.addEventListener('dblclick', () => {
    setSidebarWidth(SIDEBAR_DEFAULT_W);
    localStorage.setItem(STORAGE_KEY_SIDEBAR_W, String(SIDEBAR_DEFAULT_W));
  });
}

// ─── Sidebar Toggle ────────────────────────────────────────
export function toggleSidebar() {
  sidebarVisible = !sidebarVisible;
  applySidebarVisibility();
  localStorage.setItem(STORAGE_KEY_SIDEBAR_VIS, String(sidebarVisible));
}

// ─── Init ──────────────────────────────────────────────────
export function initSidebar() {
  applySidebarVisibility();
  initSidebarResize();

  document.getElementById('sidebar-toggle-inner').addEventListener('click', toggleSidebar);

  let treeRefreshTimer = null;
  document.addEventListener('shelves:file-change', () => {
    clearTimeout(treeRefreshTimer);
    treeRefreshTimer = setTimeout(fetchTree, 500);
  });

  document.addEventListener('shelves:active-file-changed', () => highlightActiveFile());

  fetchTree();
}
