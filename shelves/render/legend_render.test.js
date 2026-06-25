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
