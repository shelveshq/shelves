// Runs preview.js::showErrorOverlay under node with a minimal DOM stub.
//
// Usage: node run_error_overlay.mjs '<json>'
//   json: { "errors": [...] | null, "title": "..." (optional) }
// Prints: { "display": <error-overlay display>, "html": <error-overlay innerHTML> }
//
// preview.js only touches document.getElementById at import time, so a
// recording stub is enough to exercise the overlay DOM writes the way the
// browser does (same approach as run_label_patch.mjs for label_patch.js).

const els = new Map();

function stubEl(id) {
  if (!els.has(id)) {
    els.set(id, {
      id,
      style: {},
      innerHTML: '',
      textContent: '',
      classList: {
        _set: new Set(),
        add(c) { this._set.add(c); },
        remove(c) { this._set.delete(c); },
        toggle(c, force) { force ? this._set.add(c) : this._set.delete(c); },
        contains(c) { return this._set.has(c); },
      },
      addEventListener() {},
      appendChild() {},
      querySelector() { return null; },
      querySelectorAll() { return []; },
    });
  }
  return els.get(id);
}

globalThis.document = {
  getElementById: stubEl,
  querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener() {},
  createElement: (tag) => stubEl(`created-${tag}-${els.size}`),
};

const input = JSON.parse(process.argv[2]);
const { showErrorOverlay } = await import(
  new URL('../../shelves/studio/static/js/preview.js', import.meta.url)
);

if (input.title !== undefined) {
  showErrorOverlay(input.errors, input.title);
} else {
  showErrorOverlay(input.errors);
}

const overlay = stubEl('error-overlay');
console.log(JSON.stringify({
  display: overlay.style.display ?? null,
  html: overlay.innerHTML,
}));
