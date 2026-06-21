// Unit tests for compound_fit.js pure sizing math.
//
// Run with node's built-in test runner (zero dependencies, no npm install):
//   node --test shelves/render/compound_fit.test.js
//
// Only the pure functions (computeGridFit / solveAxis / shape detection) are
// covered here — the browser measure+resize loop is verified manually by
// rendering to PNG (see shelves/render/CLAUDE.md).

const test = require('node:test');
const assert = require('node:assert');
const fit = require('./compound_fit.js');

test('solveAxis: single cell takes the whole budget, gap untouched', () => {
  assert.deepStrictEqual(fit.solveAxis(376, 1, 10), { size: 376, spacing: 10 });
});

test('solveAxis: large cells cap the gap at the base spacing', () => {
  // 2 cells in 556px -> cells ~273 (> NATURAL 200) -> gap stays at base 10.
  const r = fit.solveAxis(556, 2, 10);
  assert.strictEqual(r.spacing, 10);
  assert.strictEqual(r.size, 273); // floor((556 - 10) / 2)
});

test('solveAxis: compressed cells shrink the gap below the base', () => {
  // 3 cells in 554px -> cells ~178 (< NATURAL 200) -> gap shrinks to 9.
  const r = fit.solveAxis(554, 3, 10);
  assert.strictEqual(r.spacing, 9);
  assert.strictEqual(r.size, 178); // floor((554 - 9*2) / 3)
});

test('solveAxis: gap never drops below the floor', () => {
  const r = fit.solveAxis(40, 4, 10); // tiny budget, many cells
  assert.ok(r.spacing >= fit.MIN_SPACING);
  assert.ok(r.size >= 1);
});

test('solveAxis: zero base spacing stays zero (no floor forced)', () => {
  assert.deepStrictEqual(fit.solveAxis(300, 3, 0), { size: 100, spacing: 0 });
});

test('computeGridFit: vconcat (cols=1) fills width, distributes height evenly', () => {
  const f = fit.computeGridFit({
    containerW: 436, containerH: 654, rows: 3, cols: 1,
    chromeW: 60, chromeH: 100, baseSpacing: 10,
  });
  // width: single column -> full (436 - 60) = 376
  assert.strictEqual(f.cellW, 376);
  assert.strictEqual(f.spacingX, 10);
  // height: solveAxis(654 - 100 = 554, 3) -> 178 / gap 9
  assert.strictEqual(f.cellH, 178);
  assert.strictEqual(f.spacingY, 9);
});

test('computeGridFit: hconcat (rows=1) fills height, distributes width evenly', () => {
  const f = fit.computeGridFit({
    containerW: 436, containerH: 354, rows: 1, cols: 3,
    chromeW: 65, chromeH: 80, baseSpacing: 10,
  });
  // width: solveAxis(436 - 65 = 371, 3) -> 119 / gap 6
  assert.strictEqual(f.cellW, 119);
  assert.strictEqual(f.spacingX, 6);
  // height: single row -> full (354 - 80) = 274
  assert.strictEqual(f.cellH, 274);
  assert.strictEqual(f.spacingY, 10);
});

test('computeGridFit: facet-style grid distributes both axes', () => {
  const f = fit.computeGridFit({
    containerW: 800, containerH: 600, rows: 2, cols: 2,
    chromeW: 50, chromeH: 40, baseSpacing: 20,
  });
  // A 2x2 grid returns one cellW/cellH applied to every cell -> inherently even.
  assert.ok(f.cellW > 0 && f.cellH > 0);
  // Verify the fit invariant: cells + one gap + chrome stay within the box.
  const usedW = 2 * f.cellW + f.spacingX + 50;
  const usedH = 2 * f.cellH + f.spacingY + 40;
  assert.ok(usedW <= 800);
  assert.ok(usedH <= 600);
});

test('computeGridFit: defaults rows/cols to 1 and baseSpacing to DEFAULT', () => {
  const f = fit.computeGridFit({ containerW: 300, containerH: 200, chromeW: 0, chromeH: 0 });
  assert.strictEqual(f.cellW, 300);
  assert.strictEqual(f.cellH, 200);
});

test('facetCellWidth: divides the box width by columns minus gaps', () => {
  // 2 columns in 780px with 20px gap -> (780 - 20) / 2 = 380
  assert.strictEqual(fit.facetCellWidth(780, 2, 20), 380);
  // single column -> full width
  assert.strictEqual(fit.facetCellWidth(780, 1, 20), 780);
  // floors and never goes below 1
  assert.strictEqual(fit.facetCellWidth(10, 5, 20), 1);
});

test('compoundKind: detects each compound key and rejects single views', () => {
  assert.strictEqual(fit.compoundKind({ vconcat: [] }), 'vconcat');
  assert.strictEqual(fit.compoundKind({ hconcat: [] }), 'hconcat');
  assert.strictEqual(fit.compoundKind({ facet: {}, spec: {} }), 'facet');
  assert.strictEqual(fit.compoundKind({ repeat: {}, spec: {} }), 'repeat');
  assert.strictEqual(fit.compoundKind({ mark: 'bar', encoding: {} }), null);
  assert.strictEqual(fit.compoundKind(null), null);
});

test('gridShape: concat shapes, plus facet/repeat grids', () => {
  assert.strictEqual(fit.gridShape({ vconcat: [1, 2, 3] }, 'vconcat').rows, 3);
  assert.strictEqual(fit.gridShape({ hconcat: [1, 2] }, 'hconcat').cols, 2);
  // facet with data → grid
  const f = fit.gridShape(
    { facet: { field: 'r' }, columns: 2, spec: {},
      data: { values: [{ r: 'a' }, { r: 'b' }, { r: 'c' }] } }, 'facet');
  assert.deepStrictEqual({ rows: f.rows, cols: f.cols }, { rows: 2, cols: 2 }); // ceil(3/2)=2
  // facet without data → null (width-only fallback)
  assert.strictEqual(fit.gridShape({ facet: { field: 'r' }, spec: {} }, 'facet'), null);
  // repeat → grid from array length
  assert.strictEqual(fit.gridShape({ repeat: { row: ['a', 'b'] }, spec: {} }, 'repeat').rows, 2);
});

// ── KAN-294: facet/repeat grid shape + sizing ────────────────────────────────

test('distinctCount: counts distinct non-null values', () => {
  const v = [{ r: 'A' }, { r: 'B' }, { r: 'A' }, { r: 'C' }, { r: 'B' }];
  assert.strictEqual(fit.distinctCount(v, 'r'), 3);
});

test('distinctCount: null/undefined field and non-arrays are 0', () => {
  assert.strictEqual(fit.distinctCount(null, 'r'), 0);
  assert.strictEqual(fit.distinctCount([{ x: 1 }], 'r'), 1); // one distinct value: undefined
  assert.strictEqual(fit.distinctCount([], 'r'), 0);
});

test('facetGrid: wrap facet uses columns and distinct(field)', () => {
  const spec = {
    facet: { field: 'region', type: 'nominal' },
    columns: 2,
    spec: { mark: 'bar', encoding: {} },
    data: { values: [{ region: 'N' }, { region: 'S' }, { region: 'E' }, { region: 'W' }, { region: 'C' }] },
  };
  assert.deepStrictEqual(fit.facetGrid(spec), { rows: 3, cols: 2 }); // ceil(5/2)=3
});

test('facetGrid: row facet → rows=distinct, cols=1', () => {
  const spec = {
    facet: { row: { field: 'cat', type: 'nominal' } },
    spec: {},
    data: { values: [{ cat: 'a' }, { cat: 'b' }, { cat: 'c' }, { cat: 'a' }] },
  };
  assert.deepStrictEqual(fit.facetGrid(spec), { rows: 3, cols: 1 });
});

test('facetGrid: column facet → rows=1, cols=distinct', () => {
  const spec = {
    facet: { column: { field: 'cat', type: 'nominal' } },
    spec: {},
    data: { values: [{ cat: 'a' }, { cat: 'b' }, { cat: 'c' }] },
  };
  assert.deepStrictEqual(fit.facetGrid(spec), { rows: 1, cols: 3 });
});

test('facetGrid: grid facet → rows=distinct(row), cols=distinct(column)', () => {
  const spec = {
    facet: { row: { field: 'r' }, column: { field: 'c' } },
    spec: {},
    data: { values: [
      { r: 'x', c: '1' }, { r: 'x', c: '2' }, { r: 'x', c: '3' }, { r: 'y', c: '1' },
    ] },
  };
  assert.deepStrictEqual(fit.facetGrid(spec), { rows: 2, cols: 3 });
});

test('facetGrid: missing data.values → null (caller falls back to width-only)', () => {
  const spec = { facet: { field: 'region', type: 'nominal' }, columns: 2, spec: {} };
  assert.strictEqual(fit.facetGrid(spec), null);
});

test('repeatGrid: row repeat → rows=len, cols=1', () => {
  assert.deepStrictEqual(fit.repeatGrid({ repeat: { row: ['a', 'b', 'c'] }, spec: {} }),
    { rows: 3, cols: 1 });
});

test('repeatGrid: column repeat → rows=1, cols=len', () => {
  assert.deepStrictEqual(fit.repeatGrid({ repeat: { column: ['a', 'b'] }, spec: {} }),
    { rows: 1, cols: 2 });
});

test('withCellSizes: facet sets spec.spec width/height + object spacing', () => {
  const src = { facet: { field: 'r' }, columns: 2, spec: { mark: 'bar', encoding: {} } };
  const out = fit.withCellSizes(src, 'facet', 380, 180, { row: 9, column: 20 });
  assert.strictEqual(out.spec.width, 380);
  assert.strictEqual(out.spec.height, 180);
  assert.deepStrictEqual(out.spacing, { row: 9, column: 20 });
  // facet keeps bounds:"full" so each cell's header is reserved (flush would let a
  // row's headers overlap the cells above).
  assert.strictEqual(out.bounds, 'full');
  // source not mutated (deep clone)
  assert.strictEqual(src.spec.width, undefined);
});

test('withCellSizes: concat still sizes the panel list with flush bounds (regression)', () => {
  const src = { vconcat: [{ mark: 'bar' }, { mark: 'bar' }] };
  const out = fit.withCellSizes(src, 'vconcat', 300, 120, 10);
  assert.strictEqual(out.vconcat[0].width, 300);
  assert.strictEqual(out.vconcat[1].height, 120);
  assert.strictEqual(out.spacing, 10);
  assert.strictEqual(out.bounds, 'flush');
});

test('baseSpacingFor: concat default 10, facet default 20, config + explicit override', () => {
  assert.strictEqual(fit.baseSpacingFor({ vconcat: [] }, 'vconcat'), 10);
  assert.strictEqual(fit.baseSpacingFor({ facet: {}, spec: {} }, 'facet'), 20);
  assert.strictEqual(
    fit.baseSpacingFor({ facet: {}, spec: {}, config: { facet: { spacing: 15 } } }, 'facet'), 15);
  assert.strictEqual(fit.baseSpacingFor({ vconcat: [], spacing: 4 }, 'vconcat'), 4);
});

test('computeGridFit: 3x2 facet grid fits the box with chrome', () => {
  const f = fit.computeGridFit({
    containerW: 780, containerH: 580, rows: 3, cols: 2,
    chromeW: 40, chromeH: 90, baseSpacing: 20,
  });
  const usedW = 2 * f.cellW + f.spacingX + 40;
  const usedH = 3 * f.cellH + 2 * f.spacingY + 90;
  assert.ok(usedW <= 780 && usedH <= 580);
  assert.ok(f.cellW > 0 && f.cellH > 0);
});
