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
  // Size legend types are not implemented yet → empty markup. Warn so the empty
  // box is never a silent mystery. (Use channel size: a linear color scale now
  // renders a gradient.)
  const sizeScale = fakeScale('linear', {});
  sizeScale.domain = () => [0, 10];
  const view = fakeView({ size: sizeScale });
  const div = fakeDiv({ 'data-source': 'sheet-x', 'data-scale': 'size', 'data-channel': 'size' });
  const warns = captureWarns(() => lr.populate(view, 'sheet-x', fakeDoc([div])));
  assert.strictEqual(div.innerHTML, '');
  assert.strictEqual(warns.length, 1);
  assert.ok(/no content/i.test(warns[0]));
});

// ─── SHE-12: gradient (quantitative color) renderer ────────────────

// Linear color scale over [lo, hi]; scale(v) -> a deterministic "rgb" string.
function fakeColorScale(lo, hi) {
  const s = (v) => 'rgb(' + Math.round(((v - lo) / (hi - lo)) * 255) + ',0,0)';
  s.type = 'sequential-linear';
  s.domain = () => [lo, hi];
  return s;
}

test('gradientTicks: min, mid, max from domain', () => {
  assert.deepStrictEqual(lr.gradientTicks([0, 10000]), [0, 5000, 10000]);
  // uses first & last domain entries:
  assert.deepStrictEqual(lr.gradientTicks([0, 10000, 99999]), [0, 49999.5, 99999]);
});

test('gradientStops: evenly spaced offsets + colors from scale', () => {
  const stops = lr.gradientStops(fakeColorScale(0, 100), 4);
  assert.strictEqual(stops.length, 5);
  assert.deepStrictEqual(stops.map((s) => s.offset), [0, 0.25, 0.5, 0.75, 1]);
  assert.strictEqual(stops[0].color, 'rgb(0,0,0)');
  assert.strictEqual(stops[4].color, 'rgb(255,0,0)');
});

test('gradientCss: direction + percent stops', () => {
  const css = lr.gradientCss(
    [{ offset: 0, color: 'rgb(0,0,0)' }, { offset: 1, color: 'rgb(255,0,0)' }],
    'to top'
  );
  assert.strictEqual(css, 'linear-gradient(to top, rgb(0,0,0) 0%, rgb(255,0,0) 100%)');
});

test('renderGradient: vertical bar, ticks max..min, title', () => {
  const html = lr.renderGradient(fakeColorScale(0, 10000), {
    title: 'Revenue',
    orientation: 'vertical', // format omitted -> String fallback under node
  });
  assert.ok(html.includes('Revenue')); // title heading
  assert.ok(html.includes('linear-gradient(to top')); // vertical => to top
  assert.ok(html.includes('flex-direction:column')); // ticks stacked
  // vertical display order is max..min (top to bottom):
  assert.ok(html.indexOf('>10000<') < html.indexOf('>5000<'));
  assert.ok(html.indexOf('>5000<') < html.indexOf('>0<'));
});

test('renderGradient: horizontal bar, ticks min..max', () => {
  const html = lr.renderGradient(fakeColorScale(0, 10000), { orientation: 'horizontal' });
  assert.ok(html.includes('linear-gradient(to right'));
  assert.ok(html.includes('flex-direction:row'));
  assert.ok(html.indexOf('>0<') < html.indexOf('>10000<')); // min left, max right
  assert.ok(!html.includes('font-weight:600')); // no title element when title absent
});

test('renderGradient: horizontal bar fills the container width (aligns with ticks)', () => {
  // The tick row spans the full box width (space-between); the bar must too, or
  // the bar (fixed width) and ticks (full width) visibly misalign.
  const html = lr.renderGradient(fakeColorScale(0, 10000), { orientation: 'horizontal' });
  const barStyle = html.match(/legend-gradient-bar" style="([^"]+)"/)[1];
  assert.ok(barStyle.includes('width:100%'), 'horizontal bar should fill the container width');
});

test('renderLegend: continuous color -> gradient; size/categorical unchanged', () => {
  // continuous color -> gradient
  assert.ok(lr.renderLegend(fakeColorScale(0, 100), { channel: 'color' }).includes('linear-gradient'));
  // categorical still swatches (channel irrelevant; categorical wins):
  assert.ok(lr.renderLegend(fakeScale('ordinal', { US: '#aaa' }), { channel: 'color' }).includes('legend-swatch'));
  // continuous size -> still empty (SHE-13 not implemented):
  const sizeScale = fakeScale('linear', {});
  sizeScale.domain = () => [0, 10];
  assert.strictEqual(lr.renderLegend(sizeScale, { channel: 'size' }), '');
  // continuous color but no channel -> empty (don't guess):
  assert.strictEqual(lr.renderLegend(fakeColorScale(0, 100), {}), '');
});

test('makeFormatter: vega when present, String fallback otherwise', () => {
  assert.strictEqual(lr.makeFormatter('$,.0f')(10000), '10000'); // no global vega -> String
  globalThis.vega = { formatLocale: () => ({ format: (s) => (v) => '[' + s + ']' + v }) };
  try {
    assert.strictEqual(lr.makeFormatter('$,.0f')(10000), '[$,.0f]10000');
  } finally {
    delete globalThis.vega;
  }
  assert.strictEqual(lr.makeFormatter(null)(10000), '10000'); // no spec -> String
});

test('populate: continuous color div renders a gradient', () => {
  const view = fakeView({ color: fakeColorScale(0, 10000) });
  const div = fakeDiv({
    'data-source': 'sheet-x',
    'data-scale': 'color',
    'data-channel': 'color',
    'data-title': 'Revenue',
    'data-format': '$,.0f',
  });
  const warns = captureWarns(() => lr.populate(view, 'sheet-x', fakeDoc([div])));
  assert.ok(div.innerHTML.includes('linear-gradient'));
  assert.ok(div.innerHTML.includes('Revenue'));
  assert.deepStrictEqual(warns, []);
});
