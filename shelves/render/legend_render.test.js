// Unit tests for legend_render.js pure markup core.
//   node --test shelves/render/legend_render.test.js
const test = require('node:test');
const assert = require('node:assert');
const lr = require('./legend_render.js');

function fakeScale(type, map) {
  const domain = Object.keys(map);
  const s = (v) => map[v];
  s.type = type;
  s.domain = () => domain;
  return s;
}

test('buildMarkup: vertical list with title', () => {
  const html = lr.buildMarkup(
    [{ label: 'US', color: '#1f77b4' }, { label: 'UK', color: '#ff7f0e' }],
    { title: 'Country', orientation: 'vertical' }
  );
  assert.ok(html.includes('font-weight:600'));        // title heading
  assert.ok(html.includes('Country'));
  assert.ok(html.includes('flex-direction:column'));  // vertical items
  assert.ok(html.includes('#1f77b4'));
  assert.ok(html.includes('#ff7f0e'));
  assert.ok(html.includes('>US<'));
  assert.ok(html.includes('>UK<'));
});

test('buildMarkup: horizontal wraps, no title element when absent', () => {
  const html = lr.buildMarkup(
    [{ label: 'US', color: '#000' }],
    { orientation: 'horizontal' }
  );
  assert.ok(html.includes('flex-direction:row'));
  assert.ok(html.includes('flex-wrap:wrap'));
  assert.ok(!html.includes('font-weight:600'));       // no title heading
});

test('buildMarkup: escapes HTML in labels and title', () => {
  const html = lr.buildMarkup([{ label: '<b>x</b>', color: '#000' }], { title: 'A & B <i>' });
  assert.ok(!html.includes('<b>'));
  assert.ok(!html.includes('<i>'));
  assert.ok(html.includes('&lt;b&gt;'));
  assert.ok(html.includes('&amp;'));
});

test('buildMarkup: empty domain emits title + empty items, no throw', () => {
  const html = lr.buildMarkup([], { title: 'Empty' });
  assert.ok(html.includes('Empty'));
  assert.ok(html.includes('legend-items'));
  assert.ok(!html.includes('legend-swatch'));
});

test('renderLegend: categorical types render, others empty', () => {
  const ord = fakeScale('ordinal', { US: '#aaa' });
  assert.ok(lr.renderLegend(ord, {}).includes('legend-swatch'));
  assert.ok(lr.renderLegend(fakeScale('point', { a: '#1' }), {}).includes('legend-swatch'));
  assert.ok(lr.renderLegend(fakeScale('band', { a: '#1' }), {}).includes('legend-swatch'));
  assert.strictEqual(lr.renderLegend(fakeScale('linear', {}), {}), '');
  assert.strictEqual(lr.renderLegend(fakeScale('sequential', {}), {}), '');
  assert.strictEqual(lr.renderLegend(null, {}), '');
  assert.strictEqual(lr.renderLegend({}, {}), '');
});

test('renderCategorical: maps domain through scale(value)', () => {
  const html = lr.renderLegend(fakeScale('ordinal', { US: '#aaa', UK: '#bbb' }), {
    orientation: 'vertical',
  });
  assert.ok(html.includes('#aaa'));
  assert.ok(html.includes('#bbb'));
  assert.ok(html.indexOf('US') < html.indexOf('UK'));  // domain order preserved
});

// ─── resolveScale: scale lookup with channel fallback ──────────────

// Fake Vega view: view.scale(name) returns a scale or throws; _runtime.scales
// exposes the available names (mirrors a real compiled view).
function fakeView(scales) {
  return {
    scale(name) {
      if (Object.prototype.hasOwnProperty.call(scales, name)) return scales[name];
      throw new Error('Unrecognized scale or projection: ' + name);
    },
    _runtime: { scales: scales },
  };
}

test('resolveScale: exact data-scale name wins', () => {
  const s = fakeScale('ordinal', { a: '#1' });
  const view = fakeView({ color: s });
  assert.strictEqual(lr.resolveScale(view, 'color', 'color'), s);
});

test('resolveScale: falls back to channel-suffixed scale (mark_0_color)', () => {
  // Labeled chart: VL namespaces the scale, so data-scale="color" throws but the
  // live scale is mark_0_color. The channel fallback must recover it.
  const s = fakeScale('ordinal', { a: '#1' });
  const view = fakeView({ mark_0_x: fakeScale('linear', {}), mark_0_color: s });
  assert.strictEqual(lr.resolveScale(view, 'color', 'color'), s);
});

test('resolveScale: channel fallback recovers even if data-scale is stale', () => {
  const s = fakeScale('ordinal', { a: '#1' });
  const view = fakeView({ mark_0_color: s });
  // data-scale points at a wrong/old name; channel still finds it.
  assert.strictEqual(lr.resolveScale(view, 'wrong_name', 'color'), s);
});

test('resolveScale: returns null when nothing matches', () => {
  const view = fakeView({ mark_0_x: fakeScale('linear', {}) });
  assert.strictEqual(lr.resolveScale(view, 'color', 'color'), null);
});

// ─── populate: DOM wiring + loud failures ──────────────────────────

function fakeDiv(attrs) {
  return {
    innerHTML: '',
    getAttribute(k) {
      return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null;
    },
  };
}

function fakeDoc(divs) {
  return {
    querySelectorAll(sel) {
      const m = sel.match(/data-source="([^"]+)"/);
      const src = m && m[1];
      return divs.filter((d) => d.getAttribute('data-source') === src);
    },
  };
}

function captureWarns(fn) {
  const orig = console.warn;
  const msgs = [];
  console.warn = (m) => msgs.push(String(m));
  try {
    fn();
  } finally {
    console.warn = orig;
  }
  return msgs;
}

test('populate: renders markup into the bound div via channel fallback', () => {
  const s = fakeScale('ordinal', { US: '#aaa', UK: '#bbb' });
  const view = fakeView({ mark_0_color: s });
  const div = fakeDiv({
    'data-source': 'sheet-x',
    'data-scale': 'color',     // stale (named spec) — fallback must recover
    'data-channel': 'color',
    'data-title': 'Country',
  });
  const warns = captureWarns(() => lr.populate(view, 'sheet-x', fakeDoc([div])));
  assert.ok(div.innerHTML.includes('legend-swatch'));
  assert.ok(div.innerHTML.includes('Country'));
  assert.deepStrictEqual(warns, []);
});

test('populate: warns (not silent) when the scale cannot be resolved', () => {
  const view = fakeView({ mark_0_x: fakeScale('linear', {}) });
  const div = fakeDiv({ 'data-source': 'sheet-x', 'data-scale': 'color', 'data-channel': 'color' });
  const warns = captureWarns(() => lr.populate(view, 'sheet-x', fakeDoc([div])));
  assert.strictEqual(div.innerHTML, '');
  assert.strictEqual(warns.length, 1);
  assert.ok(/could not resolve scale/i.test(warns[0]));
});

test('populate: warns when the scale resolves but renders no content', () => {
  // Gradient/size legend types are not implemented yet → empty markup. Warn so
  // the empty box is never a silent mystery.
  const view = fakeView({ color: fakeScale('linear', {}) });
  const div = fakeDiv({ 'data-source': 'sheet-x', 'data-scale': 'color', 'data-channel': 'color' });
  const warns = captureWarns(() => lr.populate(view, 'sheet-x', fakeDoc([div])));
  assert.strictEqual(div.innerHTML, '');
  assert.strictEqual(warns.length, 1);
  assert.ok(/no content/i.test(warns[0]));
});
