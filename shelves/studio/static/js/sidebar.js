// ─── Sidebar Module ────────────────────────────────────────
// File explorer tree, sidebar toggle, active file highlighting.

import { state } from './state.js';

const STORAGE_KEY_COLLAPSED   = 'shelves-studio-collapsed-dirs';
const STORAGE_KEY_SIDEBAR_VIS = 'shelves-studio-sidebar-visible';

let treeData = [];
let collapsedDirs = new Set(
  JSON.parse(localStorage.getItem(STORAGE_KEY_COLLAPSED) || '[]')
);
let sidebarVisible = localStorage.getItem(STORAGE_KEY_SIDEBAR_VIS) !== 'false';

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
    row.style.paddingLeft = (14 + depth * 18) + 'px';

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

      const name = document.createElement('span');
      name.className = 'tree-name';
      name.textContent = entry.name;

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

// ─── Sidebar Toggle ────────────────────────────────────────
export function toggleSidebar() {
  sidebarVisible = !sidebarVisible;
  const sidebar = document.getElementById('sidebar');
  if (sidebarVisible) {
    sidebar.classList.remove('collapsed');
    document.documentElement.style.setProperty('--sidebar-width', '200px');
  } else {
    sidebar.classList.add('collapsed');
    document.documentElement.style.setProperty('--sidebar-width', '0px');
  }
  localStorage.setItem(STORAGE_KEY_SIDEBAR_VIS, String(sidebarVisible));
}

// ─── Init ──────────────────────────────────────────────────
export function initSidebar() {
  if (!sidebarVisible) {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.add('collapsed');
    document.documentElement.style.setProperty('--sidebar-width', '0px');
  }

  document.getElementById('sidebar-toggle-inner').addEventListener('click', toggleSidebar);

  let treeRefreshTimer = null;
  document.addEventListener('shelves:file-change', () => {
    clearTimeout(treeRefreshTimer);
    treeRefreshTimer = setTimeout(fetchTree, 500);
  });

  document.addEventListener('shelves:active-file-changed', () => highlightActiveFile());

  fetchTree();
}
