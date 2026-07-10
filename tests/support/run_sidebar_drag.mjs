// Drives sidebar.js's resize-handle drag under node with a DOM stub,
// simulating pointerdown → pointercancel → pointermove, and reports whether
// the drag terminated. Guards the PR-59 review fix: a canceled pointer
// (touch scroll, OS gesture, lost capture) must end the drag, not leave the
// handle stuck in dragging mode.
//
// Usage: node run_sidebar_drag.mjs
// Prints: { "duringDrag": bool, "afterCancel": bool, "movedAfterCancel": bool }

function stubEl(id) {
  return {
    id,
    style: {},
    innerHTML: '',
    textContent: '',
    title: '',
    _listeners: {},
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      toggle(c, force) { force ? this._set.add(c) : this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    addEventListener(type, fn) { (this._listeners[type] ??= []).push(fn); },
    dispatch(type, ev) { for (const fn of this._listeners[type] ?? []) fn(ev); },
    setPointerCapture() {},
    releasePointerCapture() {},
    getBoundingClientRect() { return { left: 0, top: 0, width: 220, height: 800 }; },
    appendChild() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
}

const els = new Map();
function getEl(id) {
  if (!els.has(id)) els.set(id, stubEl(id));
  return els.get(id);
}

const rootProps = {};
let widthWrites = 0;

globalThis.document = {
  getElementById: getEl,
  addEventListener() {},
  querySelector() { return null; },
  querySelectorAll() { return []; },
  documentElement: {
    style: {
      setProperty(k, v) {
        rootProps[k] = v;
        if (k === '--sidebar-width') widthWrites += 1;
      },
      getPropertyValue(k) { return rootProps[k] ?? ''; },
    },
  },
};
globalThis.window = { innerWidth: 1600 };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.getComputedStyle = () => ({
  getPropertyValue: (k) => rootProps[k] ?? '',
});
globalThis.fetch = async () => ({ ok: true, json: async () => [] });

const { initSidebar } = await import(
  new URL('../../shelves/studio/static/js/sidebar.js', import.meta.url)
);
initSidebar();

const handle = getEl('sidebar-resize-handle');

handle.dispatch('pointerdown', { pointerId: 1, preventDefault() {}, clientX: 220 });
const duringDrag = handle.classList.contains('dragging');

handle.dispatch('pointercancel', { pointerId: 1 });
const afterCancel = handle.classList.contains('dragging');

const writesBefore = widthWrites;
handle.dispatch('pointermove', { clientX: 400 });
const movedAfterCancel = widthWrites > writesBefore;

console.log(JSON.stringify({ duringDrag, afterCancel, movedAfterCancel }));
