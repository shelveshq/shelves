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
  // shape legends are not implemented yet → empty markup. Warn so the empty box
  // is never a silent mystery. (size now renders; use channel 'shape' for the
  // empty path.)
  const shapeScale = fakeScale('linear', {});
  shapeScale.domain = () => [0, 10];
  const view = fakeView({ shape: shapeScale });
  const div = fakeDiv({ 'data-source': 'sheet-x', 'data-scale': 'shape', 'data-channel': 'shape' });
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
  // continuous size -> graduated glyphs (SHE-13):
  assert.ok(lr.renderLegend(fakeSizeScale(0, 100), { channel: 'size' }).includes('border-radius:50%'));
  // continuous color but no channel -> empty (don't guess):
  assert.strictEqual(lr.renderLegend(fakeColorScale(0, 100), {}), '');
  // continuous size but no channel -> empty (don't guess):
  assert.strictEqual(lr.renderLegend(fakeSizeScale(0, 100), {}), '');
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

// ─── SHE-13: size (graduated-glyph) renderer ───────────────────────

// Linear size scale over [lo, hi]; scale(v) returns the symbol AREA in px².
// Identity (area == value) keeps the diameter math easy to assert. When
// `withTicks` is true, expose a d3-style .ticks(n) returning nice endpoints so
// the scale.ticks() path is exercised; omit it to exercise the evenly-spaced
// fallback.
function fakeSizeScale(lo, hi, withTicks) {
  const s = (v) => v; // area == value
  s.type = 'linear';
  s.domain = () => [lo, hi];
  if (withTicks) {
    s.ticks = (n) => {
      const out = [];
      for (let i = 0; i < n; i++) out.push(lo + ((hi - lo) * i) / (n - 1));
      return out;
    };
  }
  return s;
}

test('areaToDiameter: area px^2 -> pixel diameter', () => {
  // area = π·r²; r=5 ⇒ area=π·25 ⇒ diameter=10.
  assert.ok(Math.abs(lr.areaToDiameter(Math.PI * 25) - 10) < 1e-9);
  assert.ok(Math.abs(lr.areaToDiameter(Math.PI * 100) - 20) < 1e-9); // r=10 ⇒ d=20
  assert.strictEqual(lr.areaToDiameter(0), 0); // zero area -> invisible glyph
  assert.strictEqual(lr.areaToDiameter(-5), 0); // guard negatives
  assert.strictEqual(lr.areaToDiameter('x'), 0); // guard non-numbers
});

test('sizeTicks: scale.ticks when present, evenly-spaced otherwise', () => {
  // No .ticks method -> evenly spaced across the domain (count incl. endpoints):
  assert.deepStrictEqual(lr.sizeTicks(fakeSizeScale(0, 100), 5), [0, 25, 50, 75, 100]);
  // With .ticks -> defer to the scale's nice values:
  assert.deepStrictEqual(lr.sizeTicks(fakeSizeScale(0, 100, true), 5), [0, 25, 50, 75, 100]);
  // Default count is 5 when omitted:
  assert.strictEqual(lr.sizeTicks(fakeSizeScale(0, 100)).length, 5);
});

test('sizeEntries: value -> area -> diameter, order preserved', () => {
  const scale = fakeSizeScale(0, 100); // area == value
  const entries = lr.sizeEntries(scale, [Math.PI * 25, Math.PI * 100]);
  assert.strictEqual(entries.length, 2);
  assert.strictEqual(entries[0].value, Math.PI * 25);
  assert.ok(Math.abs(entries[0].diameter - 10) < 1e-9);
  assert.ok(Math.abs(entries[1].diameter - 20) < 1e-9);
});

test('buildSizeMarkup: glyphs sized, labels aligned, title', () => {
  const html = lr.buildSizeMarkup(
    [{ label: '$0', diameter: 0 }, { label: '$5,000', diameter: 20 }],
    { title: 'Revenue', orientation: 'vertical', maxDiameter: 20 }
  );
  assert.ok(html.includes('Revenue')); // title heading
  assert.ok(html.includes('font-weight:600')); // title style
  assert.ok(html.includes('border-radius:50%')); // circle glyph
  assert.ok(html.includes('width:20px;height:20px')); // largest glyph at its diameter
  assert.ok(html.includes('flex-direction:column')); // vertical items
  assert.ok(html.includes('>$0<'));
  assert.ok(html.includes('>$5,000<'));
});

test('renderSize: vertical graduated glyphs, ascending, title', () => {
  const html = lr.renderSize(fakeSizeScale(0, 10000), {
    title: 'Revenue',
    orientation: 'vertical', // format omitted -> String fallback under node
  });
  assert.ok(html.includes('Revenue')); // title heading
  assert.ok(html.includes('border-radius:50%')); // circle glyphs
  assert.ok(html.includes('flex-direction:column'));
  // 5 default stops over [0, 10000] -> labels 0,2500,5000,7500,10000 ascending:
  assert.ok(html.indexOf('>0<') < html.indexOf('>10000<')); // smallest before largest
});

test('renderSize: horizontal row of glyphs', () => {
  const html = lr.renderSize(fakeSizeScale(0, 10000), { orientation: 'horizontal' });
  assert.ok(html.includes('flex-direction:row'));
  assert.ok(html.includes('align-items:flex-end')); // circles sit on a shared baseline
  assert.ok(html.includes('border-radius:50%'));
  assert.ok(!html.includes('font-weight:600')); // no title element when title absent
});

test('renderSize: empty for non-numeric or <2 domain', () => {
  const bad = fakeSizeScale(0, 0);
  bad.domain = () => ['a']; // non-numeric, single entry
  assert.strictEqual(lr.renderSize(bad, {}), '');
  const empty = fakeSizeScale(0, 0);
  empty.domain = () => [];
  assert.strictEqual(lr.renderSize(empty, {}), '');
});

test('populate: size div renders graduated glyphs', () => {
  const view = fakeView({ size: fakeSizeScale(0, 10000) });
  const div = fakeDiv({
    'data-source': 'sheet-x',
    'data-scale': 'size',
    'data-channel': 'size',
    'data-title': 'Revenue',
    'data-format': '$,.0f',
  });
  const warns = captureWarns(() => lr.populate(view, 'sheet-x', fakeDoc([div])));
  assert.ok(div.innerHTML.includes('border-radius:50%'));
  assert.ok(div.innerHTML.includes('Revenue'));
  assert.deepStrictEqual(warns, []);
});
