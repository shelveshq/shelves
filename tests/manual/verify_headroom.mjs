// Manual verification harness for KAN-289 scale headroom.
//
// Usage:
//   1. Build a compiled-Vega file for a fixture (see steps below).
//   2. node verify_headroom.mjs <vg.json> <scaleName> <factor> <max|min>
//
// It injects sample data (max revenue = 1000), runs charterPatch, then prints
// the resolved scale domain BEFORE and AFTER the patch and PASS/FAIL against
// the expected expansion. Requires `vega` (npm i vega@5 in a scratch dir).
import fs from 'fs';
import * as vega from 'vega';

const [, , vgPath, scaleName, factorStr, dir] = process.argv;
const factor = parseFloat(factorStr);
const extendMax = dir === 'max';

// Load charter_patch.js as a global script (same trick the PNG harness uses).
globalThis.window = globalThis;
new Function(
  fs.readFileSync(new URL('../../shelves/render/charter_patch.js', import.meta.url), 'utf8')
)();

const SAMPLE = [
  { country: 'US', revenue: 1000, order_count: 40, week: '2024-01-01' },
  { country: 'UK', revenue: 600, order_count: 25, week: '2024-01-08' },
  { country: 'FR', revenue: 250, order_count: 12, week: '2024-01-15' },
];

function withData(spec) {
  const s = JSON.parse(JSON.stringify(spec));
  for (const d of s.data) if (d.name === 'source') d.values = SAMPLE;
  return s;
}
async function domainOf(spec, name) {
  const view = new vega.View(vega.parse(spec), { renderer: 'none' });
  await view.runAsync();
  return view.scale(name).domain();
}

const raw = JSON.parse(fs.readFileSync(vgPath, 'utf8'));
const before = await domainOf(withData(raw), scaleName);
const patched = window.charterPatch(withData(raw)); // patch mutates+returns
const after = await domainOf(patched, scaleName);

const rawExtent = 1000; // max revenue in SAMPLE
const span = 1000;      // zero-based: span ≈ max
const expected = extendMax
  ? rawExtent + factor * span // lower bound on domain max (nice may round up)
  : -(factor * span);          // upper bound on domain min (nice may round down)

const ok = extendMax ? after[1] >= expected - 1e-6 : after[0] <= expected + 1e-6;
console.log('scale     :', scaleName);
console.log('before    :', before);
console.log('after     :', after);
console.log('expected  :', extendMax ? `domain[1] >= ${expected}` : `domain[0] <= ${expected}`);
console.log(ok ? 'PASS' : 'FAIL');
process.exit(ok ? 0 : 1);
