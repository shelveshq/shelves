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

test('gridShape: concat shapes; null for facet/repeat (KAN-294)', () => {
  assert.deepStrictEqual(
    { rows: fit.gridShape({ vconcat: [1, 2, 3] }, 'vconcat').rows, cols: fit.gridShape({ vconcat: [1, 2, 3] }, 'vconcat').cols },
    { rows: 3, cols: 1 },
  );
  const h = fit.gridShape({ hconcat: [1, 2] }, 'hconcat');
  assert.strictEqual(h.rows, 1);
  assert.strictEqual(h.cols, 2);
  assert.strictEqual(fit.gridShape({ facet: {} }, 'facet'), null);
});
