// Test runner for charter_patch.js — applies window.charterPatch to a compiled
// Vega spec and prints the patched spec as JSON. Pure spec transform: no vega,
// no canvas, no network. Used by tests/test_charter_patch_js.py to assert the
// browser-side label patch's behavior directly.
//
// Usage: node run_charter_patch.mjs <spec.json>
import fs from 'fs';

globalThis.window = globalThis;
new Function(
  fs.readFileSync(
    new URL('../../shelves/render/charter_patch.js', import.meta.url),
    'utf8',
  ),
)();

const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
process.stdout.write(JSON.stringify(window.charterPatch(spec)));
