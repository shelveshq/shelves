// Unit tests for control_render.js pure markup core.
//   node --test shelves/render/control_render.test.js
const test = require('node:test');
const assert = require('node:assert');
const cr = require('./control_render.js');

test('buildDropdown: renders select with options and default', () => {
  const html = cr.buildDropdown({
    param: 'metric',
    title: 'Metric',
    options: [
      { value: 'revenue', label: 'Revenue' },
      { value: 'cost', label: 'Cost' },
    ],
    default: 'revenue',
  });
  assert.ok(html.includes('<select'));
  assert.ok(html.includes('value="revenue"'));
  assert.ok(html.includes('value="cost"'));
  assert.ok(html.includes('>Revenue<'));
  assert.ok(html.includes('>Cost<'));
  assert.ok(html.includes('selected'));
  assert.ok(html.includes('Metric'));
});

test('buildDropdown: escapes HTML in labels and title', () => {
  const html = cr.buildDropdown({
    param: 'x',
    title: 'A & B',
    options: [{ value: '<script>', label: '<b>bad</b>' }],
    default: null,
  });
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<b>'));
  assert.ok(html.includes('&lt;'));
  assert.ok(html.includes('&amp;'));
});

test('buildDropdown: null default means no option selected', () => {
  const html = cr.buildDropdown({
    param: 'x',
    title: 'X',
    options: [{ value: 'a', label: 'A' }],
    default: null,
  });
  assert.ok(!html.includes('selected'));
});

test('buildStepper: renders number input with min/max/step', () => {
  const html = cr.buildStepper({
    param: 'top_n',
    title: 'Top N',
    default: '10',
    min: '5',
    max: '50',
    step: '5',
  });
  assert.ok(html.includes('<input'));
  assert.ok(html.includes('type="number"'));
  assert.ok(html.includes('min="5"'));
  assert.ok(html.includes('max="50"'));
  assert.ok(html.includes('step="5"'));
  assert.ok(html.includes('value="10"'));
  assert.ok(html.includes('Top N'));
});

test('buildDateInput: renders date input with min/max', () => {
  const html = cr.buildDateInput({
    param: 'as_of',
    title: 'As Of',
    default: '2025-01-01',
    min: '2024-01-01',
    max: '2026-12-31',
  });
  assert.ok(html.includes('<input'));
  assert.ok(html.includes('type="date"'));
  assert.ok(html.includes('min="2024-01-01"'));
  assert.ok(html.includes('max="2026-12-31"'));
  assert.ok(html.includes('value="2025-01-01"'));
  assert.ok(html.includes('As Of'));
});

test('buildTextInput: renders text input', () => {
  const html = cr.buildTextInput({
    param: 'search',
    title: 'Search',
    default: 'hello',
  });
  assert.ok(html.includes('<input'));
  assert.ok(html.includes('type="text"'));
  assert.ok(html.includes('value="hello"'));
  assert.ok(html.includes('Search'));
});

test('buildControl: dispatches to correct widget by data-control', () => {
  const dropdown = cr.buildControl({
    param: 'metric', control: 'dropdown', title: 'M',
    options: JSON.stringify([{ value: 'a', label: 'A' }]),
    default: 'a',
  });
  assert.ok(dropdown.includes('<select'));

  const stepper = cr.buildControl({
    param: 'top_n', control: 'stepper', title: 'N',
    default: '10', min: '5', max: '50', step: '5',
  });
  assert.ok(stepper.includes('type="number"'));

  const date = cr.buildControl({
    param: 'as_of', control: 'date', title: 'D',
    default: '2025-01-01', min: '2024-01-01', max: '2026-12-31',
  });
  assert.ok(date.includes('type="date"'));

  const text = cr.buildControl({
    param: 'search', control: 'text', title: 'S', default: '',
  });
  assert.ok(text.includes('type="text"'));
});

test('buildControl: unknown widget returns empty string', () => {
  const html = cr.buildControl({
    param: 'x', control: 'slider', title: 'X', default: '0',
  });
  assert.strictEqual(html, '');
});

test('escapeAttr: escapes attribute-significant characters', () => {
  assert.ok(cr.escapeAttr('"hello"').includes('&quot;'));
  assert.ok(cr.escapeAttr('<tag>').includes('&lt;'));
  assert.ok(cr.escapeAttr('a&b').includes('&amp;'));
});
