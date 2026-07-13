// Fake @xterm/xterm + @xterm/addon-fit for the node harness
// (run_terminal_open.mjs). terminal.js imports these via the
// __shelvesXtermSrc / __shelvesXtermFitSrc overrides — node cannot import
// the real https: CDN modules. Lifecycle calls are recorded into
// globalThis.__termEvents so the harness can assert ordering.

// Created Terminal instances, in creation order, so the harness can read
// back what was written into each (visible-failure assertions).
export const instances = [];

export class Terminal {
  constructor(opts) {
    this.opts = opts;
    instances.push(this);
    this.element = null;     // set by open(), like real xterm
    this.lines = [];         // writeln record
    this.writes = 0;         // raw write() count
    this.rows = 24;
    this.cols = 80;
    this.disposed = false;
    globalThis.__termEvents?.push('term-created');
  }
  loadAddon(addon) { addon._terminal = this; }
  open(el) {
    this.element = el;
    globalThis.__termEvents?.push('term-open');
  }
  write() { this.writes += 1; }
  writeln(s) { this.lines.push(String(s)); }
  onData(cb) { this._dataCb = cb; }
  dispose() { this.disposed = true; }
}

export class FitAddon {
  fit() {
    // Real FitAddon no-ops without an opened terminal; mirror that so a
    // fit-before-open regression shows up as ordering, not a crash.
    if (this._terminal?.element) globalThis.__termEvents?.push('fit');
  }
}
