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

// ─── buildMultiSelect ────────────────────────────────────────

test('buildMultiSelect: renders checkboxes with All toggle', () => {
  const html = cr.buildMultiSelect({
    title: 'Region',
    options: [
      { value: 'EMEA', label: 'EMEA' },
      { value: 'APAC', label: 'APAC' },
      { value: 'NA', label: 'North America' },
    ],
    default: null,
  });
  assert.ok(html.includes('shelves-control'));
  assert.ok(html.includes('Region'));
  assert.ok(html.includes('type="checkbox"'));
  // "All" toggle
  assert.ok(html.includes('value="__all__"'));
  // Each option
  assert.ok(html.includes('value="EMEA"'));
  assert.ok(html.includes('value="APAC"'));
  assert.ok(html.includes('value="NA"'));
  assert.ok(html.includes('> EMEA<'));
  assert.ok(html.includes('> North America<'));
});

test('buildMultiSelect: default array checks matching options', () => {
  const html = cr.buildMultiSelect({
    title: 'Region',
    options: [
      { value: 'EMEA', label: 'EMEA' },
      { value: 'APAC', label: 'APAC' },
    ],
    default: ['EMEA'],
  });
  // EMEA should be checked
  assert.ok(html.includes('value="EMEA" checked'));
  // APAC should not
  assert.ok(!html.includes('value="APAC" checked'));
});

test('buildMultiSelect: null default means All checked', () => {
  const html = cr.buildMultiSelect({
    title: 'X',
    options: [{ value: 'a', label: 'A' }],
    default: null,
  });
  assert.ok(html.includes('value="__all__" checked'));
});

test('buildMultiSelect: escapes option values and labels', () => {
  const html = cr.buildMultiSelect({
    title: 'X',
    options: [{ value: '<xss>', label: 'A & B' }],
    default: null,
  });
  assert.ok(!html.includes('<xss>'));
  assert.ok(html.includes('&lt;xss&gt;'));
  assert.ok(html.includes('A &amp; B'));
});

// ─── buildRangeStub ──────────────────────────────────────────

test('buildRangeStub: renders disabled placeholder', () => {
  const html = cr.buildRangeStub({ title: 'Discount', control: 'range' });
  assert.ok(html.includes('shelves-control'));
  assert.ok(html.includes('Discount'));
  assert.ok(html.includes('range'));
  // Should NOT contain an input or select
  assert.ok(!html.includes('<input'));
  assert.ok(!html.includes('<select'));
});

test('buildRangeStub: works for date_range too', () => {
  const html = cr.buildRangeStub({ title: 'Date', control: 'date_range' });
  assert.ok(html.includes('date_range'));
});

// ─── buildNativeMultiSelect (multi, dropdown:true) ───────────

test('buildNativeMultiSelect: renders <select multiple> with options', () => {
  const html = cr.buildNativeMultiSelect({
    field: 'category',
    title: 'Category',
    options: [
      { value: 'Furniture', label: 'Furniture' },
      { value: 'Technology', label: 'Technology' },
    ],
    default: null,
  });
  assert.ok(html.includes('<select multiple'));
  assert.ok(html.includes('value="Furniture"'));
  assert.ok(html.includes('value="Technology"'));
  // No "All" option — empty selection means unfiltered.
  assert.ok(!html.includes('>All<'));
  // Null default selects nothing.
  assert.ok(!html.includes('selected'));
});

test('buildNativeMultiSelect: sizes the listbox to show multiple rows', () => {
  // A one-row-tall fixed height clips its own options; the widget must request
  // a few rows via `size` (clamped to [2, 6]) so it reads as a multi-select.
  const two = cr.buildNativeMultiSelect({
    field: 'x',
    options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }, { value: 'c', label: 'C' }],
    default: null,
  });
  assert.ok(two.includes('size="3"'));
  // Fewer than 2 options still asks for 2 rows.
  const one = cr.buildNativeMultiSelect({ field: 'x', options: [{ value: 'a', label: 'A' }], default: null });
  assert.ok(one.includes('size="2"'));
  // More than 6 clamps to 6.
  const many = cr.buildNativeMultiSelect({
    field: 'x',
    options: Array.from({ length: 10 }, (_, i) => ({ value: String(i), label: String(i) })),
    default: null,
  });
  assert.ok(many.includes('size="6"'));
  // No fixed pixel height that would clip the rows.
  assert.ok(!two.includes('height:var(--shelves'));
});

test('buildNativeMultiSelect: default array selects matching options', () => {
  const html = cr.buildNativeMultiSelect({
    field: 'category',
    title: 'Category',
    options: [
      { value: 'Furniture', label: 'Furniture' },
      { value: 'Technology', label: 'Technology' },
    ],
    default: ['Technology'],
  });
  assert.ok(html.includes('value="Technology" selected'));
  assert.ok(!html.includes('value="Furniture" selected'));
});

test('buildNativeMultiSelect: escapes option values and labels', () => {
  const html = cr.buildNativeMultiSelect({
    field: 'x',
    title: 'X',
    options: [{ value: '<script>', label: '<b>bad</b>' }],
    default: null,
  });
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<b>'));
  assert.ok(html.includes('&lt;'));
});

// ─── buildSingleList (single, dropdown:false) ────────────────

test('buildSingleList: renders radio list with All option', () => {
  const html = cr.buildSingleList({
    field: 'region',
    model: 'file_orders',
    title: 'Region',
    options: [
      { value: 'West', label: 'West' },
      { value: 'East', label: 'East' },
    ],
    default: 'West',
  });
  assert.ok(html.includes('type="radio"'));
  assert.ok(html.includes('>All<') || html.includes('> All<'));
  assert.ok(html.includes('value="West" checked'));
  // "All" radio is not checked when a value is set.
  assert.ok(!html.includes('value="" checked'));
});

test('buildSingleList: null default checks All', () => {
  const html = cr.buildSingleList({
    field: 'region',
    title: 'Region',
    options: [{ value: 'West', label: 'West' }],
    default: null,
  });
  assert.ok(html.includes('value="" checked'));
});

// ─── buildControl: filter dispatch ───────────────────────────

test('buildControl: dispatches multi_select', () => {
  const html = cr.buildControl({
    control: 'multi_select',
    title: 'Region',
    options: JSON.stringify([{ value: 'a', label: 'A' }]),
    default: null,
  });
  assert.ok(html.includes('type="checkbox"'));
});

test('buildControl: dispatches multi_dropdown to native select', () => {
  const html = cr.buildControl({
    control: 'multi_dropdown',
    title: 'Category',
    field: 'category',
    options: JSON.stringify([{ value: 'a', label: 'A' }]),
    default: null,
  });
  assert.ok(html.includes('<select multiple'));
});

test('buildControl: dispatches single_list to radio list', () => {
  const html = cr.buildControl({
    control: 'single_list',
    title: 'Region',
    field: 'region',
    options: JSON.stringify([{ value: 'a', label: 'A' }]),
    default: null,
  });
  assert.ok(html.includes('type="radio"'));
});

test('buildControl: dispatches range/date_range to stub', () => {
  const range = cr.buildControl({ control: 'range', title: 'R', default: null });
  assert.ok(range.includes('range'));
  assert.ok(!range.includes('<input'));

  const dateRange = cr.buildControl({ control: 'date_range', title: 'DR', default: null });
  assert.ok(dateRange.includes('date_range'));
});

// ─── buildStaticValue ────────────────────────────────────────

test('buildStaticValue: dropdown shows option label, not value', () => {
  const html = cr.buildStaticValue({
    control: 'dropdown',
    title: 'Metric',
    default: 'cost',
    options: [
      { value: 'revenue', label: 'Revenue' },
      { value: 'cost', label: 'Cost' },
    ],
  });
  assert.ok(html.includes('Metric'));
  assert.ok(html.includes('Cost'));
  assert.ok(!html.includes('<select'));
  assert.ok(!html.includes('<input'));
  assert.ok(!html.includes('disabled'));
});

test('buildStaticValue: dropdown null default shows All', () => {
  const html = cr.buildStaticValue({
    control: 'dropdown',
    title: 'Region',
    default: null,
    options: [{ value: 'EMEA', label: 'EMEA' }],
    mode: 'single',
  });
  assert.ok(html.includes('All'));
});

test('buildStaticValue: stepper shows number', () => {
  const html = cr.buildStaticValue({
    control: 'stepper',
    title: 'Top N',
    default: 10,
  });
  assert.ok(html.includes('Top N'));
  assert.ok(html.includes('10'));
  assert.ok(!html.includes('<input'));
});

test('buildStaticValue: date shows ISO date', () => {
  const html = cr.buildStaticValue({
    control: 'date',
    title: 'As Of',
    default: '2025-06-01',
  });
  assert.ok(html.includes('2025-06-01'));
  assert.ok(!html.includes('<input'));
});

test('buildStaticValue: text shows value or em-dash when empty', () => {
  const withVal = cr.buildStaticValue({
    control: 'text',
    title: 'Search',
    default: 'hello',
  });
  assert.ok(withVal.includes('hello'));

  const empty = cr.buildStaticValue({
    control: 'text',
    title: 'Search',
    default: '',
  });
  assert.ok(empty.includes('—'));
});

test('buildStaticValue: multi mode comma-joins labels', () => {
  const html = cr.buildStaticValue({
    control: 'multi_select',
    title: 'Region',
    default: ['EMEA', 'APAC'],
    options: [
      { value: 'EMEA', label: 'EMEA' },
      { value: 'APAC', label: 'Asia Pacific' },
      { value: 'NA', label: 'NA' },
    ],
    mode: 'multi',
  });
  assert.ok(html.includes('EMEA'));
  assert.ok(html.includes('Asia Pacific'));
  assert.ok(!html.includes('<input'));
});

test('buildStaticValue: multi mode null default shows All', () => {
  const html = cr.buildStaticValue({
    control: 'multi_select',
    title: 'Region',
    default: null,
    options: [{ value: 'a', label: 'A' }],
    mode: 'multi',
  });
  assert.ok(html.includes('All'));
});

test('buildStaticValue: wildcard mode shows contains text', () => {
  const html = cr.buildStaticValue({
    control: 'text',
    title: 'Search',
    default: 'foo',
    mode: 'wildcard',
  });
  assert.ok(html.includes('contains'));
  assert.ok(html.includes('foo'));
});

test('buildStaticValue: wildcard mode empty shows All', () => {
  const html = cr.buildStaticValue({
    control: 'text',
    title: 'Search',
    default: null,
    mode: 'wildcard',
  });
  assert.ok(html.includes('All'));
});

test('buildStaticValue: range mode shows min-max', () => {
  const html = cr.buildStaticValue({
    control: 'range',
    title: 'Discount',
    default: [0.1, 0.5],
    mode: 'range',
  });
  assert.ok(html.includes('0.1'));
  assert.ok(html.includes('0.5'));
  assert.ok(html.includes('–')); // en-dash
});

test('buildStaticValue: at_least mode shows ≥', () => {
  const html = cr.buildStaticValue({
    control: 'stepper',
    title: 'Min',
    default: 100,
    mode: 'at_least',
  });
  assert.ok(html.includes('≥')); // ≥
  assert.ok(html.includes('100'));
});

test('buildStaticValue: at_most mode shows ≤', () => {
  const html = cr.buildStaticValue({
    control: 'stepper',
    title: 'Max',
    default: 50,
    mode: 'at_most',
  });
  assert.ok(html.includes('≤')); // ≤
  assert.ok(html.includes('50'));
});

test('buildStaticValue: after mode shows on or after', () => {
  const html = cr.buildStaticValue({
    control: 'date',
    title: 'Start',
    default: '2025-01-01',
    mode: 'after',
  });
  assert.ok(html.includes('on or after'));
  assert.ok(html.includes('2025-01-01'));
});

test('buildStaticValue: before mode shows on or before', () => {
  const html = cr.buildStaticValue({
    control: 'date',
    title: 'End',
    default: '2025-12-31',
    mode: 'before',
  });
  assert.ok(html.includes('on or before'));
  assert.ok(html.includes('2025-12-31'));
});

test('buildStaticValue: escapes values', () => {
  const html = cr.buildStaticValue({
    control: 'text',
    title: '<script>',
    default: '<b>xss</b>',
  });
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<b>'));
  assert.ok(html.includes('&lt;'));
});

test('buildStaticValue: range mode null default shows All', () => {
  const html = cr.buildStaticValue({
    control: 'range',
    title: 'Price',
    default: null,
    mode: 'range',
  });
  assert.ok(html.includes('All'));
});
