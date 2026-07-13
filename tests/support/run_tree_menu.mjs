// Drives sidebar.js's file-management UI (SHE-42) under node with a mini-DOM:
// group-header "+" → inline create input, right-click context menu
// (New / Rename / Duplicate / two-step Delete), inline rename, duplicate,
// and menu dismissal. Records every fetch and the resulting DOM facts.
//
// Usage: node run_tree_menu.mjs
// Prints one JSON dict; tests/test_studio_tree_menu.py asserts its fields.

// ─── Mini-DOM ──────────────────────────────────────────────
class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.style = {};
    this.value = '';
    this.title = '';
    this.placeholder = '';
    this.id = '';
    this._text = '';
    this._innerHTML = '';
    this._classes = new Set();
    this._listeners = {};
    this.classList = {
      add: (c) => this._classes.add(c),
      remove: (c) => this._classes.delete(c),
      toggle: (c, force) => (force ? this._classes.add(c) : this._classes.delete(c)),
      contains: (c) => this._classes.has(c),
    };
  }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this._classes].join(' '); }
  set textContent(v) { this._text = String(v); }
  get textContent() { return this._text; }
  set innerHTML(v) { this._innerHTML = String(v); if (v === '') this.children = []; }
  get innerHTML() { return this._innerHTML; }
  appendChild(c) { c.remove?.(); c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c, ref) {
    c.remove?.();
    c.parentNode = this;
    const i = ref ? this.children.indexOf(ref) : -1;
    if (i < 0) this.children.push(c);
    else this.children.splice(i, 0, c);
    return c;
  }
  get nextSibling() {
    if (!this.parentNode) return null;
    const i = this.parentNode.children.indexOf(this);
    return this.parentNode.children[i + 1] ?? null;
  }
  remove() {
    if (!this.parentNode) return;
    const i = this.parentNode.children.indexOf(this);
    if (i >= 0) this.parentNode.children.splice(i, 1);
    this.parentNode = null;
  }
  contains(el) { for (let e = el; e; e = e.parentNode) if (e === this) return true; return false; }
  addEventListener(t, f) { (this._listeners[t] ??= []).push(f); }
  removeEventListener(t, f) {
    const a = this._listeners[t];
    const i = a ? a.indexOf(f) : -1;
    if (i >= 0) a.splice(i, 1);
  }
  dispatch(t, ev = {}) {
    ev.target ??= this;
    ev.stopPropagation ??= () => {};
    ev.preventDefault ??= () => {};
    for (const f of [...(this._listeners[t] ?? [])]) f(ev);
  }
  focus() {}
  select() {}
  getBoundingClientRect() { return { left: 0, top: 0, width: 180, height: 120, right: 180, bottom: 120 }; }
  _matches(sel) {
    // Supports: tag, .cls(.cls…), and an optional [data-path="…"] suffix.
    const m = /^([a-zA-Z]+)?((?:\.[\w-]+)*)(?:\[data-path="(.*)"\])?$/.exec(sel);
    if (!m) return false;
    const [, tag, cls, dataPath] = m;
    if (tag && this.tagName !== tag.toUpperCase()) return false;
    for (const c of (cls ?? '').split('.').filter(Boolean)) {
      if (!this._classes.has(c)) return false;
    }
    if (dataPath !== undefined && this.dataset.path !== dataPath) return false;
    return true;
  }
  querySelectorAll(sel) {
    const out = [];
    const walk = (el) => {
      for (const c of el.children) {
        if (c._matches(sel)) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] ?? null; }
}

const docRoot = new El('root');
const body = docRoot.appendChild(new El('body'));
const byId = new Map();
function getEl(id) {
  if (!byId.has(id)) {
    const el = new El('div');
    el.id = id;
    docRoot.appendChild(el);
    byId.set(id, el);
  }
  return byId.get(id);
}
for (const id of [
  'file-tree', 'sidebar', 'sidebar-header', 'sidebar-rail',
  'sidebar-toggle-inner', 'sidebar-resize-handle', 'workspace',
]) getEl(id);

const docListeners = {};
globalThis.document = {
  body,
  getElementById: getEl,
  createElement: (tag) => new El(tag),
  addEventListener: (t, f) => { (docListeners[t] ??= []).push(f); },
  removeEventListener: (t, f) => {
    const a = docListeners[t];
    const i = a ? a.indexOf(f) : -1;
    if (i >= 0) a.splice(i, 1);
  },
  dispatchEvent: (ev) => { for (const f of [...(docListeners[ev.type] ?? [])]) f(ev); },
  querySelector: (sel) => docRoot.querySelector(sel),
  querySelectorAll: (sel) => docRoot.querySelectorAll(sel),
  documentElement: {
    style: { setProperty() {}, getPropertyValue() { return ''; } },
  },
};
function docDispatch(type, ev = {}) {
  ev.type = type;
  ev.stopPropagation ??= () => {};
  ev.preventDefault ??= () => {};
  document.dispatchEvent(ev);
}

globalThis.CustomEvent = class {
  constructor(type, opts = {}) { this.type = type; this.detail = opts.detail; }
};
globalThis.CSS = { escape: (s) => s };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.alert = (msg) => { out.alerts.push(String(msg)); };

const opened = [];
globalThis.window = {
  innerWidth: 1600,
  innerHeight: 900,
  addEventListener() {},
  removeEventListener() {},
  shelvesStudio: { openFile: (p) => opened.push(p) },
};

// ─── Fetch stub ────────────────────────────────────────────
const TREE = [{
  name: 'charts', type: 'dir', path: 'charts', group: 'charts',
  children: [{ name: 'a.yaml', type: 'file', path: 'charts/a.yaml' }],
}];
const fetchLog = [];
globalThis.fetch = async (url, opts = {}) => {
  const method = opts.method ?? 'GET';
  fetchLog.push({ url, method, body: opts.body ?? null });
  const respond = (ok, status, jsonBody, textBody = '') => ({
    ok, status,
    json: async () => jsonBody,
    text: async () => textBody,
  });
  if (url === '/project') return respond(true, 200, TREE);
  if (method === 'GET' && url.startsWith('/file?path=charts%2Fa.yaml')) {
    return respond(true, 200, { content: 'sheet: a\n', path: 'charts/a.yaml' });
  }
  if (method === 'POST' && url.startsWith('/file?') && url.includes('dup.yaml')) {
    return respond(false, 409, null, 'File already exists');
  }
  if (method === 'POST' || method === 'DELETE') return respond(true, method === 'POST' ? 201 : 200, { ok: true });
  return respond(true, 200, {});
};

const tick = () => new Promise((r) => setImmediate(r));
async function flush(n = 5) { for (let i = 0; i < n; i++) await tick(); }

const out = { alerts: [] };

// ─── Session ───────────────────────────────────────────────
const { state } = await import(new URL('../../shelves/studio/static/js/state.js', import.meta.url));
const { initSidebar } = await import(new URL('../../shelves/studio/static/js/sidebar.js', import.meta.url));
initSidebar();
await flush();

const ft = getEl('file-tree');
const groupRow = () => ft.querySelector('.tree-dir[data-path="charts"]');
const fileRow = () => ft.querySelector('.tree-file[data-path="charts/a.yaml"]');
const inputRow = () => ft.querySelector('.tree-input');
const menu = () => body.querySelector('.tree-menu');
const menuItemEls = () => (menu() ? menu().querySelectorAll('.sh-menu-item') : []);

// 1. create via group "+"
const addBtn = groupRow()?.querySelector('.tree-add');
out.addButtonExists = !!addBtn;
addBtn?.dispatch('click', {});
out.createInputAppears = !!inputRow();
{
  const input = inputRow()?.querySelector('input');
  if (input) {
    input.value = 'newchart';
    input.dispatch('keydown', { key: 'Enter' });
    await flush();
  }
}
const createCall = fetchLog.find((c) => c.method === 'POST' && c.url.startsWith('/file?'));
out.createUrl = createCall?.url ?? null;
out.createMethod = createCall?.method ?? null;
out.openedAfterCreate = opened[0] ?? null;
out.treeRefetched = fetchLog.filter((c) => c.url === '/project').length >= 2;

// 2. create conflict → input stays, is-error
groupRow()?.querySelector('.tree-add')?.dispatch('click', {});
{
  const input = inputRow()?.querySelector('input');
  if (input) {
    input.value = 'dup.yaml';
    input.dispatch('keydown', { key: 'Enter' });
    await flush();
    out.dupInputStays = !!inputRow();
    out.dupInputError = input.classList.contains('is-error');
    input.dispatch('keydown', { key: 'Escape' });
  }
}

// 3. escape cancels a fresh input
groupRow()?.querySelector('.tree-add')?.dispatch('click', {});
{
  const input = inputRow()?.querySelector('input');
  input?.dispatch('keydown', { key: 'Escape' });
  out.escRemovedInput = !inputRow();
}

// 4. context menu on a file row
{
  let prevented = false;
  fileRow()?.dispatch('contextmenu', {
    clientX: 100, clientY: 100, preventDefault: () => { prevented = true; },
  });
  out.menuPreventedDefault = prevented;
  out.menuItems = menuItemEls().map((el) => el.textContent);
}

// 5. delete is two-step
{
  const items = menuItemEls();
  const del = items[items.length - 1];
  const deletesBefore = fetchLog.filter((c) => c.method === 'DELETE').length;
  del?.dispatch('click', {});
  out.deleteFirstClickLabel = del?.textContent ?? null;
  out.noDeleteFetchYet = fetchLog.filter((c) => c.method === 'DELETE').length === deletesBefore;
  del?.dispatch('click', {});
  await flush();
  const delCall = fetchLog.find((c) => c.method === 'DELETE');
  out.deleteUrl = delCall?.url ?? null;
  out.deleteMethod = delCall?.method ?? null;
  out.menuClosedAfterDelete = !menu();
}

// 6. rename updates the open file's path and clears fileDeleted
state.currentFile = { path: 'charts/a.yaml', dirty: false };
state.fileDeleted = true;   // simulate the rename's deleted(old) broadcast racing in
{
  fileRow()?.dispatch('contextmenu', { clientX: 100, clientY: 100 });
  const rename = menuItemEls().find((el) => el.textContent === 'Rename');
  rename?.dispatch('click', {});
  const input = fileRow()?.querySelector('input');
  out.renamePrefill = input?.value ?? null;
  if (input) {
    input.value = 'b.yaml';
    input.dispatch('keydown', { key: 'Enter' });
    await flush();
  }
  const renameCall = fetchLog.find((c) => c.url.startsWith('/file/rename?'));
  out.renameUrl = renameCall?.url ?? null;
  out.currentFileAfterRename = state.currentFile?.path ?? null;
  out.fileDeletedCleared = state.fileDeleted === false;
}

// 7. duplicate copies content into stem-copy.ext
{
  const getsBefore = fetchLog.length;
  fileRow()?.dispatch('contextmenu', { clientX: 100, clientY: 100 });
  const dup = menuItemEls().find((el) => el.textContent === 'Duplicate');
  dup?.dispatch('click', {});
  await flush();
  const calls = fetchLog.slice(getsBefore);
  out.duplicateGet = calls.find((c) => c.method === 'GET' && c.url.startsWith('/file?'))?.url ?? null;
  const post = calls.find((c) => c.method === 'POST' && c.url.startsWith('/file?'));
  out.duplicatePostUrl = post?.url ?? null;
  out.duplicateBody = post?.body ?? null;
}

// 8. click outside dismisses the menu
{
  fileRow()?.dispatch('contextmenu', { clientX: 100, clientY: 100 });
  const opened_ = !!menu();
  docDispatch('click', { target: body });
  out.menuClosedOnOutsideClick = opened_ && !menu();
}

console.log(JSON.stringify(out));
