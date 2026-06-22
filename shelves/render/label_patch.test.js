// Unit tests for label_patch.js — the pure compile-then-patch transform.
//
// Run with node's built-in test runner (zero dependencies, no npm install):
//   node --test shelves/render/label_patch.test.js
//
// These assert on the SHAPE of the emitted Vega marks (signal/expression
// strings), which is deterministic. Visual placement is still verified by
// rendering to PNG (see shelves/render/CLAUDE.md) — these only lock the
// expression construction that PNG review cannot cheaply regression-guard.

const test = require('node:test');
const assert = require('node:assert');

// label_patch.js is a plain global script: requiring it attaches `labelPatch`
// to globalThis (window is undefined under node).
require('./label_patch.js');
const labelPatch = globalThis.labelPatch;

function intent(overrides) {
  return Object.assign(
    {
      markName: 'mark_0',
      field: 'revenue',
      type: 'quantitative',
      format: null,
      horizontal: null,
      vertical: null,
      size: 11,
      color: null,
    },
    overrides || {},
  );
}

// A compiled single-unit heatmap: a rect with two band axes and the measure on
// fill, no x2/y2.
function heatmapSpec(labelOverrides) {
  return {
    usermeta: { shelves: { labels: [intent(labelOverrides)] } },
    marks: [
      {
        name: 'mark_0',
        type: 'rect',
        from: { data: 'source_0' },
        encode: {
          update: {
            x: { scale: 'x', field: 'product' },
            y: { scale: 'y', field: 'country' },
            fill: { scale: 'color', field: 'revenue' },
          },
        },
      },
    ],
  };
}

// ── Heatmap fit gate (KAN-307) ──────────────────────────────────────────────

test('heatmap fit gate coerces the value to a string before length() (unformatted)', () => {
  // Regression: an unformatted numeric measure made width = length(number),
  // which does not return digit count -> the gate misfired and hid every label.
  const spec = heatmapSpec({ format: null });
  labelPatch(spec);
  const op = spec.marks[1].encode.update.opacity.signal;
  assert.ok(
    op.includes("length('' + (datum['revenue']))"),
    'opacity signal must measure the string form, got: ' + op,
  );
});

test('heatmap fit gate measures the formatted string length when a format is set', () => {
  const spec = heatmapSpec({ format: '$,.0f' });
  labelPatch(spec);
  const op = spec.marks[1].encode.update.opacity.signal;
  assert.ok(
    op.includes("length('' + (format(datum['revenue'], '$,.0f')))"),
    'opacity signal should length() the formatted string, got: ' + op,
  );
});

test('heatmap fit gate checks BOTH cell width and cell height', () => {
  const spec = heatmapSpec({ format: '$,.0f', size: 11 });
  labelPatch(spec);
  const op = spec.marks[1].encode.update.opacity.signal;
  assert.ok(op.includes("bandwidth('x')"), 'width gate missing: ' + op);
  assert.ok(op.includes("bandwidth('y')"), 'height gate missing: ' + op);
  assert.ok(op.includes('11 <='), 'font-height check missing: ' + op);
});

test('heatmap text channel keeps the raw value expression (no display change)', () => {
  const spec = heatmapSpec({ format: null });
  labelPatch(spec);
  assert.strictEqual(spec.marks[1].encode.update.text.signal, "datum['revenue']");
});

// ── Dispatch guard (KAN-307) ────────────────────────────────────────────────

test('a stack-encoded bar rect (carries x2/y2) is NOT routed to the heatmap builder', () => {
  const spec = {
    usermeta: { shelves: { labels: [intent({ format: '$,.0f' })] } },
    marks: [
      {
        name: 'mark_0',
        type: 'rect',
        from: { data: 'source_0' },
        encode: {
          update: {
            x: { scale: 'x', field: 'product' },
            y: { scale: 'y', field: 'revenue_end' },
            y2: { scale: 'y', field: 'revenue_start' },
          },
        },
      },
    ],
  };
  labelPatch(spec);
  const text = spec.marks[1];
  assert.ok(text, 'a label mark should be inserted for the bar');
  const op = text.encode.update.opacity;
  const isHeatmap = !!(op && op.signal && /bandwidth/.test(op.signal));
  assert.ok(!isHeatmap, 'a bar must use the label-transform path, not the heatmap fit gate');
});

// ── Shared text-signal helper (refactor lock, KAN-307) ──────────────────────

test('point label text signal is unchanged by the shared helper extraction', () => {
  const spec = {
    usermeta: { shelves: { labels: [intent({ format: '$,.0f' })] } },
    marks: [
      {
        name: 'mark_0',
        type: 'symbol',
        from: { data: 'source_0' },
        encode: {
          update: {
            x: { scale: 'x', field: 'a' },
            y: { scale: 'y', field: 'revenue' },
            fill: { scale: 'color', field: 'cat' },
          },
        },
      },
    ],
  };
  labelPatch(spec);
  assert.strictEqual(
    spec.marks[1].encode.update.text.signal,
    "format(datum.datum['revenue'], '$,.0f')",
  );
});
