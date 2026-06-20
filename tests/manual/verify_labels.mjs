// Manual verification harness for KAN-283 collision-aware label placement.
//
// Usage:
//   1. Build a compiled-Vega file for a fixture:
//        .venv/bin/python -c "import json,sys; from shelves.translator.translate \
//          import translate_chart; from shelves.schema.chart_schema import parse_chart; \
//          from tests.conftest import MODELS_DIR; \
//          print(json.dumps(translate_chart(parse_chart(open(sys.argv[1]).read()), \
//          models_dir=MODELS_DIR)))" tests/fixtures/yaml/label_bar_simple.yaml > /tmp/vl.json
//        npx -p vega-lite@6 -p vega vl2vg /tmp/vl.json > /tmp/vg.json
//   2. node verify_labels.mjs /tmp/vg.json
//
// It injects sample data, runs labelPatch, renders headless, then prints every
// label's resolved text/x/y/opacity and checks two invariants:
//   (1) no two VISIBLE labels overlap, (2) the harness reports any auto-hidden
//   labels (opacity 0) so you can confirm they are the expected dense/small ones.
// Requires `vega` (npm i vega@5 in a scratch dir, like verify_headroom.mjs).
import fs from 'fs';
import * as vega from 'vega';

const [, , vgPath] = process.argv;

globalThis.window = globalThis;
new Function(
  fs.readFileSync(new URL('../../shelves/render/label_patch.js', import.meta.url), 'utf8')
)();

const SAMPLE = [
  { country: 'US', revenue: 1000, order_count: 40, week: '2024-01-01' },
  { country: 'UK', revenue: 600, order_count: 25, week: '2024-01-08' },
  { country: 'FR', revenue: 250, order_count: 12, week: '2024-01-15' },
  { country: 'DE', revenue: 980, order_count: 38, week: '2024-01-22' },
];

function withData(spec) {
  const s = JSON.parse(JSON.stringify(spec));
  for (const d of s.data || []) if (d.name === 'source') d.values = SAMPLE;
  return s;
}

function collectText(item, out) {
  if (item.marktype === 'text' && item.items) out.push(...item.items);
  (item.items || []).forEach((c) => collectText(c, out));
}

function overlaps(a, b) {
  return !(a.bounds.x2 < b.bounds.x1 || b.bounds.x2 < a.bounds.x1 ||
           a.bounds.y2 < b.bounds.y1 || b.bounds.y2 < a.bounds.y1);
}

const raw = JSON.parse(fs.readFileSync(vgPath, 'utf8'));
const patched = window.labelPatch(withData(raw));
const view = new vega.View(vega.parse(patched), { renderer: 'none' });
await view.runAsync();

const items = [];
collectText(view.scenegraph().root, items);

const visible = items.filter((t) => t.opacity > 0);
const hidden = items.filter((t) => !(t.opacity > 0));

console.log('labels total   :', items.length);
console.log('labels visible :', visible.length);
console.log('labels hidden  :', hidden.length);
items.forEach((t) =>
  console.log('  ', JSON.stringify({
    text: t.text, x: Math.round(t.x), y: Math.round(t.y), opacity: t.opacity,
  })));

let bad = 0;
for (let i = 0; i < visible.length; i++) {
  for (let j = i + 1; j < visible.length; j++) {
    if (overlaps(visible[i], visible[j])) {
      bad++;
      console.log('OVERLAP:', visible[i].text, '<->', visible[j].text);
    }
  }
}
console.log(bad === 0 ? 'PASS (no visible overlaps)' : 'FAIL (' + bad + ' overlaps)');
process.exit(bad === 0 ? 0 : 1);
