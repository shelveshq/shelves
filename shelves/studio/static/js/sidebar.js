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
    row.style.paddingLeft = (depth * 16) + 'px';

    if (entry.type === 'dir') {
      row.className = 'tree-dir';
      row.dataset.path = entry.path;

      const chevron = document.createElement('span');
      chevron.className = 'tree-chevron';
      chevron.textContent = collapsedDirs.has(entry.path) ? '\u25b6' : '\u25bc';

      const icon = document.createElement('span');
      icon.className = 'tree-icon';
      icon.textContent = '\ud83d\udcc1';

      const name = document.createElement('span');
      name.className = 'tree-name';
      name.textContent = entry.name;

      row.appendChild(chevron);
      row.appendChild(icon);
      row.appendChild(name);
      row.addEventListener('click', () => toggleDir(entry.path));
      container.appendChild(row);

      if (!collapsedDirs.has(entry.path) && entry.children?.length) {
        container.appendChild(renderTreeLevel(entry.children, depth + 1));
      }
    } else {
      row.className = 'tree-file';
      row.dataset.path = entry.path;

      const icon = document.createElement('span');
      icon.className = 'tree-icon';
      icon.textContent = entry.name.endsWith('.json') ? '\ud83d\udcc4' : '\ud83d\udcca';

      const name = document.createElement('span');
      name.className = 'tree-name';
      name.textContent = entry.name;

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

// ─── Sidebar Toggle ────────────────────────────────────────
function toggleSidebar() {
  sidebarVisible = !sidebarVisible;
  const sidebar = document.getElementById('sidebar');
  const workspace = document.getElementById('workspace');
  const toggleBtn = document.getElementById('sidebar-toggle');
  if (sidebarVisible) {
    sidebar.classList.remove('collapsed');
    workspace.style.gridTemplateColumns = '';
    toggleBtn.textContent = '\u2630';
  } else {
    sidebar.classList.add('collapsed');
    workspace.style.gridTemplateColumns = '0px var(--editor-width, 1fr) 6px 1fr';
    toggleBtn.textContent = '\u25b6';
  }
  localStorage.setItem(STORAGE_KEY_SIDEBAR_VIS, String(sidebarVisible));
}

// ─── Init ──────────────────────────────────────────────────
export function initSidebar() {
  // Apply initial sidebar visibility
  if (!sidebarVisible) {
    const sidebar = document.getElementById('sidebar');
    const workspace = document.getElementById('workspace');
    const toggleBtn = document.getElementById('sidebar-toggle');
    sidebar.classList.add('collapsed');
    workspace.style.gridTemplateColumns = '0px var(--editor-width, 1fr) 6px 1fr';
    toggleBtn.textContent = '\u25b6';
  }

  // Toggle buttons
  document.getElementById('sidebar-toggle').addEventListener('click', toggleSidebar);
  document.getElementById('sidebar-toggle-inner').addEventListener('click', toggleSidebar);

  // Refresh tree on file changes (debounced)
  let treeRefreshTimer = null;
  document.addEventListener('shelves:file-change', () => {
    clearTimeout(treeRefreshTimer);
    treeRefreshTimer = setTimeout(fetchTree, 500);
  });

  // Re-highlight when active file changes
  document.addEventListener('shelves:active-file-changed', () => highlightActiveFile());

  // Initial tree load
  fetchTree();
}
