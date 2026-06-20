// compound_fit.js — browser-side sizing for Vega-Lite COMPOUND specs.
//
// Compound specs (vconcat/hconcat/concat/facet/repeat) don't support
// width/height:"container", so they can't responsively fit a box the way a
// single view can. Estimating the per-panel pixel size in Python is brittle:
// it needs the rendered size of axes and titles, which depends on real text
// metrics we cannot measure without a browser.
//
// This module measures in the browser instead. After an initial probe render
// it reads the actual rendered size from the Vega scenegraph, derives the
// "chrome" (axes + title + spacing that is NOT plot area), and re-renders with
// per-panel plot sizes that make the whole thing fit the target box exactly.
//
// Split, mirroring label_patch.js: Python owns intent (emit the compound spec
// + the target box); JS owns mechanics (measure + size). Authored as a plain
// global script so it works both inlined into a file:// page and required by
// node's built-in test runner. The pure math (`computeGridFit`/`solveAxis`) has
// no DOM dependency and is unit-tested with `node --test`.
(function (global) {
  'use strict';

  // Base inter-cell gap (px) at a cell's "natural" size. Matches the Python
  // STACKED_CONCAT_SPACING the compiler emits; below NATURAL_CELL_PX the gap
  // shrinks proportionally (see solveAxis).
  var DEFAULT_SPACING = 10;
  // Cell size (px) at which the base spacing is "natural" (Vega-Lite's default
  // continuous view size).
  var NATURAL_CELL_PX = 200;
  // Floor so a heavily compressed grid never collapses its gaps to nothing.
  var MIN_SPACING = 2;

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  function assign(target) {
    for (var i = 1; i < arguments.length; i++) {
      var src = arguments[i];
      if (!src) continue;
      for (var k in src) {
        if (Object.prototype.hasOwnProperty.call(src, k)) target[k] = src[k];
      }
    }
    return target;
  }

  // ── Pure sizing math (no DOM; unit-tested) ─────────────────────────────────

  // Distribute `avail` px across `count` even cells whose gap is a fixed
  // fraction of the cell size — so the gap shrinks WITH the cells when the grid
  // is compressed. The gap is capped at `baseSpacing` (never grows past the
  // natural value) and floored at MIN_SPACING. Returns { size, spacing }.
  function solveAxis(avail, count, baseSpacing) {
    avail = Math.max(1, avail);
    if (count <= 1) return { size: avail, spacing: baseSpacing };
    var ratio = baseSpacing > 0 ? baseSpacing / NATURAL_CELL_PX : 0;
    // Solve avail = count*size + (count-1)*ratio*size for size.
    var size0 = avail / (count + (count - 1) * ratio);
    var spacing = baseSpacing > 0
      ? clamp(Math.round(ratio * size0), MIN_SPACING, baseSpacing)
      : 0;
    var size = Math.max(1, Math.floor((avail - spacing * (count - 1)) / count));
    return { size: size, spacing: spacing };
  }

  // Given the target box, the grid shape (rows x cols), and the measured chrome
  // (px of axes/title that is NOT cell plot area), return even cell sizes and
  // the per-axis gap. Concat is a degenerate grid (cols=1 for vconcat, rows=1
  // for hconcat); facet/repeat pass their real rows x cols.
  function computeGridFit(o) {
    var rows = Math.max(1, o.rows | 0);
    var cols = Math.max(1, o.cols | 0);
    var baseSpacing = (o.baseSpacing == null) ? DEFAULT_SPACING : o.baseSpacing;
    var h = solveAxis(o.containerW - (o.chromeW || 0), cols, baseSpacing);
    var v = solveAxis(o.containerH - (o.chromeH || 0), rows, baseSpacing);
    return { cellW: h.size, cellH: v.size, spacingX: h.spacing, spacingY: v.spacing };
  }

  // Per-cell width for a faceted/repeated grid given its column count. Width-only:
  // used as the no-bound-data fallback (see fitFacet). The full grid fit (height
  // too) goes through computeGridFit when the grid shape is known.
  function facetCellWidth(containerW, columns, spacing) {
    columns = Math.max(1, columns | 0);
    return Math.max(1, Math.floor((containerW - spacing * (columns - 1)) / columns));
  }

  // Count distinct values of `field` across an array of row objects. Non-arrays and
  // falsy `field` → 0. null/undefined cell values collapse to a single bucket.
  function distinctCount(values, field) {
    if (!Array.isArray(values) || !field) return 0;
    var seen = Object.create(null);
    var n = 0;
    for (var i = 0; i < values.length; i++) {
      var row = values[i];
      if (!row || typeof row !== 'object') continue;
      var v = row[field];
      var key = (v === null || v === undefined) ? ' ' : ('v' + String(v));
      if (!(key in seen)) { seen[key] = true; n++; }
    }
    return n;
  }

  // ── Compound-spec helpers ──────────────────────────────────────────────────

  function compoundKind(spec) {
    if (!spec || typeof spec !== 'object') return null;
    if (spec.vconcat) return 'vconcat';
    if (spec.hconcat) return 'hconcat';
    if (spec.concat) return 'concat';
    if (spec.facet) return 'facet';
    if (spec.repeat) return 'repeat';
    return null;
  }

  // Top-level bound data rows, or null. Charter binds data on the TOP-LEVEL facet
  // spec (bind.py), so values live at spec.data.values.
  function dataValues(spec) {
    return (spec && spec.data && Array.isArray(spec.data.values)) ? spec.data.values : null;
  }

  // Grid (rows x cols) for a FACET spec, counted from bound data. Returns null when
  // the data isn't available (caller degrades to width-only). Shapes:
  //   wrap:        spec.facet = {field, type}, spec.columns = N
  //   row/col/grid spec.facet = {row?:{field}, column?:{field}}
  function facetGrid(spec) {
    var f = spec && spec.facet;
    if (!f) return null;
    var values = dataValues(spec);
    if (!values) return null;                      // no bound data → width-only fallback
    if (typeof f.field === 'string') {             // wrap facet
      var cols = (spec.columns | 0) || 1;
      var n = distinctCount(values, f.field);
      if (n <= 0) return null;
      return { rows: Math.ceil(n / cols), cols: cols };
    }
    var rowField = f.row && f.row.field;           // row / column / grid facet
    var colField = f.column && f.column.field;
    var rows = rowField ? distinctCount(values, rowField) : 1;
    var cols2 = colField ? distinctCount(values, colField) : 1;
    if ((rowField && rows <= 0) || (colField && cols2 <= 0)) return null;
    return { rows: Math.max(1, rows), cols: Math.max(1, cols2) };
  }

  // Grid for a REPEAT spec — panel count is a compile-time constant (array lengths),
  // so no data is needed. spec.repeat = {row?:[...], column?:[...]}.
  function repeatGrid(spec) {
    var r = spec && spec.repeat;
    if (!r) return null;
    var rows = Array.isArray(r.row) ? r.row.length : 1;
    var cols = Array.isArray(r.column) ? r.column.length : 1;
    return { rows: Math.max(1, rows), cols: Math.max(1, cols) };
  }

  // Grid shape for a compound spec. vconcat stacks rows (cols=1); hconcat stacks
  // columns (rows=1); facet/repeat carry rows x cols (no panel list — sized via the
  // inner spec.spec). Returns null when a facet grid can't be resolved from data
  // (→ width-only fallback) or for unknown kinds.
  function gridShape(spec, kind) {
    if (kind === 'vconcat') return { rows: spec.vconcat.length, cols: 1, panels: spec.vconcat };
    if (kind === 'hconcat') return { rows: 1, cols: spec.hconcat.length, panels: spec.hconcat };
    if (kind === 'facet') return facetGrid(spec);   // {rows, cols} | null
    if (kind === 'repeat') return repeatGrid(spec); // {rows, cols}
    return null;
  }

  // Clone `spec` with cells sized to cellW x cellH and the given spacing. Concat
  // sizes each panel in its list; facet/repeat size the single inner spec.spec.
  // `spacing` is a scalar for concat or a {row, column} object for a facet/repeat
  // grid.
  //
  // Bounds differ by kind. Concat panels have no per-cell header, so bounds:"flush"
  // packs their plot areas tightly and uniformly. Facet/repeat cells DO have a
  // header drawn above each cell; under "flush" the inter-row spacing reserves no
  // room for it, so a row's headers overlap the cells of the row above (the
  // collapsed-row-gap bug). bounds:"full" reserves each cell's header/axis in the
  // layout, turning the proportionally-reduced spacing into a clean gap.
  function withCellSizes(spec, kind, cellW, cellH, spacing) {
    var s = clone(spec);
    if (kind === 'facet' || kind === 'repeat') {
      s.spec = assign({}, s.spec, { width: cellW, height: cellH });
      if (s.bounds == null) s.bounds = 'full';
    } else {
      var panels = s[kind];
      for (var i = 0; i < panels.length; i++) {
        panels[i].width = cellW;
        panels[i].height = cellH;
      }
      if (s.bounds == null) s.bounds = 'flush';
    }
    s.spacing = spacing;
    return s;
  }

  // Default facet cell gap (Vega-Lite's default), overridable via config.facet.spacing.
  var FACET_SPACING_DEFAULT = 20;

  // Base inter-cell gap for the spec's kind: concat uses spec.spacing or
  // DEFAULT_SPACING (10); facet/repeat use spec.spacing, else config.facet.spacing,
  // else FACET_SPACING_DEFAULT (20).
  function baseSpacingFor(spec, kind) {
    if (typeof spec.spacing === 'number') return spec.spacing;
    if (kind === 'facet' || kind === 'repeat') {
      var cfg = spec.config || {};
      if (cfg.facet && typeof cfg.facet.spacing === 'number') return cfg.facet.spacing;
      return FACET_SPACING_DEFAULT;
    }
    return DEFAULT_SPACING;
  }

  // Width-only fit for facet/repeat: size each cell to the box width using the
  // compile-time column count. Height stays Vega's default. This is the fallback
  // used by fit() only when the grid shape can't be resolved from bound data; the
  // full grid fit (height too) is the primary path. One embed, no measurement.
  function fitFacet(target, vlSpec, box, embedOpts) {
    var columns = vlSpec.columns || 1;
    var spacing = FACET_SPACING_DEFAULT;
    var cfg = vlSpec.config || {};
    if (cfg.facet && typeof cfg.facet.spacing === 'number') spacing = cfg.facet.spacing;
    var cellW = facetCellWidth(box.width, columns, spacing);
    var s = clone(vlSpec);
    if (s.spec) s.spec = assign({}, s.spec, { width: cellW }); // facet/repeat cell spec
    else s.width = cellW;
    return global.vegaEmbed(target, s, embedOpts);
  }

  // ── Runtime: two-pass measure → resize → re-render (browser only) ───────────

  // Fit a compound Vega-Lite spec to `box` ({width, height}) and embed it into
  // `target`. Single-view specs fall through to a plain embed.
  // Returns the vegaEmbed result promise for the final render.
  function fit(target, vlSpec, box, embedOpts) {
    embedOpts = embedOpts || {};
    var kind = compoundKind(vlSpec);
    var shape = kind ? gridShape(vlSpec, kind) : null;
    if (!shape) {
      // facet/repeat we couldn't shape (no bound data) → width-only fallback;
      // anything else (single view / unknown) → plain embed.
      if (kind === 'facet' || kind === 'repeat') {
        return fitFacet(target, vlSpec, box, embedOpts);
      }
      return global.vegaEmbed(target, vlSpec, embedOpts);
    }

    var rows = shape.rows;
    var cols = shape.cols;
    var baseSpacing = baseSpacingFor(vlSpec, kind);

    var el = (typeof target === 'string') ? document.querySelector(target) : target;
    // Hide during the probe pass so the user only sees the fitted render (visibility,
    // not display, so layout/scenegraph still compute).
    if (el) el.style.visibility = 'hidden';

    // Probe at a container-derived cell size (a first approximation that ignores
    // chrome), NOT a tiny fixed size. The chart title spans the full width and
    // sits ABOVE the plots, so it is vertical chrome — but the scenegraph's total
    // width is max(titleWidth, plotRowWidth). With a tiny probe the narrow plot
    // row lets the title dominate totalW, inflating the horizontal chrome and
    // leaving a gap (the vconcat right-gap bug). Sizing the probe plots near the
    // container makes the plot row dominate, so the measured chrome is the real
    // axis chrome. Chrome is ~size-invariant, so one correction pass converges.
    var probeW = Math.max(1, Math.floor(box.width / cols));
    var probeH = Math.max(1, Math.floor(box.height / rows));
    var probe = withCellSizes(vlSpec, kind, probeW, probeH, baseSpacing);
    return global.vegaEmbed(target, probe, assign({}, embedOpts, { actions: false }))
      .then(function (r1) {
        var b = r1.view.scenegraph().root.bounds;
        var totalW = b.x2 - b.x1;
        var totalH = b.y2 - b.y1;
        // Plot area the probe occupied (cells + inter-cell gaps); the remainder
        // is chrome (axes, title, headers) — invariant to cell size.
        var gridPlotW = cols * probeW + (cols - 1) * baseSpacing;
        var gridPlotH = rows * probeH + (rows - 1) * baseSpacing;
        var chromeW = Math.max(0, totalW - gridPlotW);
        var chromeH = Math.max(0, totalH - gridPlotH);
        if (r1.finalize) r1.finalize();

        var f = computeGridFit({
          containerW: box.width,
          containerH: box.height,
          rows: rows,
          cols: cols,
          chromeW: chromeW,
          chromeH: chromeH,
          baseSpacing: baseSpacing,
        });
        var spacing = (kind === 'facet' || kind === 'repeat')
          ? { row: f.spacingY, column: f.spacingX }   // grid: independent per-axis gaps
          : (kind === 'vconcat' ? f.spacingY : f.spacingX);   // concat: scalar
        var finalSpec = withCellSizes(vlSpec, kind, f.cellW, f.cellH, spacing);
        return global.vegaEmbed(target, finalSpec, embedOpts);
      })
      .then(function (r2) {
        if (el) el.style.visibility = '';
        return r2;
      })
      .catch(function (e) {
        if (el) el.style.visibility = '';
        // eslint-disable-next-line no-console
        console.error(e);
      });
  }

  var api = {
    computeGridFit: computeGridFit,
    solveAxis: solveAxis,
    facetCellWidth: facetCellWidth,
    distinctCount: distinctCount,
    dataValues: dataValues,
    facetGrid: facetGrid,
    repeatGrid: repeatGrid,
    baseSpacingFor: baseSpacingFor,
    compoundKind: compoundKind,
    gridShape: gridShape,
    withCellSizes: withCellSizes,
    fit: fit,
    DEFAULT_SPACING: DEFAULT_SPACING,
    NATURAL_CELL_PX: NATURAL_CELL_PX,
    MIN_SPACING: MIN_SPACING,
  };

  global.compoundFit = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
