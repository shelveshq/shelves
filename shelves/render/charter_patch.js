// charter_patch.js — single source of truth for compile-then-patch labels.
//
// Canonical browser-side label renderer shared by every rendering pipeline:
//   - shelves/render/to_html.py inlines this file into standalone HTML
//     (used by the `render` and `dev` CLIs).
//   - shelves/studio serves this file verbatim at /charter-patch.js and the
//     studio preview passes window.charterPatch to vegaEmbed.
//
// Authored as a plain (non-module) global script on purpose: it must work both
// when inlined into a file:// HTML page and when loaded via <script src> in the
// studio, matching how Vega itself is loaded. Edit here only — never copy.
(function (global) {
  // Headroom: fraction of the data span added to the measure-scale domain so an
  // edge label isn't clipped at the chart boundary (KAN-289). Tweak these to
  // trade bar length for label breathing room — higher = shorter bars, more gap.
  const HEADROOM = {
    horizontal: 0.12, // room past a horizontal bar's end (label to the right)
    vertical: 0.1, // room above a vertical bar's top (label on top)
  };

  function clone(o) {
    return JSON.parse(JSON.stringify(o));
  }

  // Find a named mark and return the chain of ancestor groups leading to it,
  // ending with the mark itself: [group, group, ..., mark]. VL appends
  // '_marks' to the compiled Vega mark name.
  function findMarkPath(marks, name, path) {
    if (!marks) return null;
    for (const m of marks) {
      if (m.name === name || m.name === name + '_marks') return path.concat(m);
      if (m.marks) {
        const found = findMarkPath(m.marks, name, path.concat(m));
        if (found) return found;
      }
    }
    return null;
  }

  function insertAfterMark(marks, target, newMark) {
    if (!marks) return false;
    for (let i = 0; i < marks.length; i++) {
      if (marks[i] === target) {
        marks.splice(i + 1, 0, newMark);
        return true;
      }
      if (marks[i].marks && insertAfterMark(marks[i].marks, target, newMark)) {
        return true;
      }
    }
    return false;
  }

  // Center of the band along the cross axis ('x' or 'y').
  //
  // Plain bars carry the band ref directly on the rect ({scale, field}); the
  // band width lives on a separate width/height signal, so we add band: 0.5 to
  // center on the band rather than its leading edge. Faceted bars (color, or a
  // row/column layout) instead fill their parent facet group via
  // height/width: {field: {group: ...}} and carry NO band ref — for those we
  // center inside the group with {field: {group: size}, mult: 0.5}.
  function bandCenter(enc, dim) {
    const sizeKey = dim === 'x' ? 'width' : 'height';
    if (enc[dim]) {
      const ref = clone(enc[dim]);
      ref.band = 0.5;
      return ref;
    }
    const size = enc[sizeKey];
    if (size && size.field && size.field.group) {
      return { field: { group: sizeKey }, mult: 0.5 };
    }
    return null;
  }

  // Measure-axis position along 'x' or 'y'. end=true → value end (bar tip),
  // end=false → value origin (bar base). Falls back to the centered ref
  // (xc/yc) used by tick and point marks.
  function measurePos(enc, axis, end) {
    const key = end ? axis : axis + '2';
    if (enc[key]) return clone(enc[key]);
    if (end && enc[axis + 'c']) return clone(enc[axis + 'c']);
    return null;
  }

  // Pixel-position expression for a measure-axis value ref, for use in signals.
  function posExpr(ref) {
    if (!ref) return null;
    if (ref.scale && ref.field) return "scale('" + ref.scale + "', datum['" + ref.field + "'])";
    if (ref.scale && 'value' in ref) return "scale('" + ref.scale + "', " + ref.value + ")";
    if (ref.signal) return '(' + ref.signal + ')';
    if ('value' in ref) return '' + ref.value;
    return null;
  }

  // Signal for the pixel midpoint between a segment's value-end (axis) and
  // value-start (axis2) — i.e. the geometric center of a stacked segment.
  function midSignal(enc, axis) {
    const a = posExpr(enc[axis]);
    const b = posExpr(enc[axis + '2']);
    return a && b ? '(' + a + ' + ' + b + ') / 2' : null;
  }

  // Extend a continuous measure scale's domain to leave room for an edge label
  // so it isn't clipped at the chart boundary (KAN-289).
  function applyHeadroom(vgSpec, scaleName, factor, extendMax) {
    var scales = vgSpec.scales;
    if (!scales) return;
    var scale = scales.find(function (s) { return s.name === scaleName; });
    if (!scale || scale.type !== 'linear') return;

    var dom = scale.domain;
    if (!dom || !dom.data) return;
    var fields = dom.fields || (dom.field ? [dom.field] : []);
    if (fields.length === 0) return;
    if (!vgSpec.data || !vgSpec.data.some(function (d) { return d.name === dom.data; })) {
      return;
    }

    var aggName = scaleName + '_hr';
    if (vgSpec.data.some(function (d) { return d.name === aggName; })) return;

    vgSpec.data.push({
      name: aggName,
      source: dom.data,
      transform: [{
        type: 'aggregate',
        fields: fields.concat(fields),
        ops: fields.map(function () { return 'min'; })
          .concat(fields.map(function () { return 'max'; })),
        as: fields.map(function (_, i) { return 'mn' + i; })
          .concat(fields.map(function (_, i) { return 'mx' + i; }))
      }]
    });

    var row = "data('" + aggName + "')[0]";
    var mxExpr = 'max(' + fields.map(function (_, i) { return row + '.mx' + i; }).join(',') + ')';
    var mnExpr = 'min(' + fields.map(function (_, i) { return row + '.mn' + i; }).join(',') + ')';
    var sMax = scaleName + '_dmax';
    var sMin = scaleName + '_dmin';

    vgSpec.signals = vgSpec.signals || [];
    vgSpec.signals.push({ name: sMax, update: row + ' ? ' + mxExpr + ' : 0' });
    vgSpec.signals.push({ name: sMin, update: row + ' ? ' + mnExpr + ' : 0' });

    var span = '(' + sMax + ' - ' + sMin + ')';
    if (extendMax) {
      scale.domainMax = { signal: sMax + ' + ' + factor + ' * ' + span };
    } else {
      scale.domainMin = { signal: sMin + ' - ' + factor + ' * ' + span };
    }
  }

  function charterPatch(vgSpec) {
    const labels = vgSpec.usermeta?.charter?.labels;
    if (!labels || labels.length === 0) return vgSpec;

    for (const intent of labels) {
      const path = findMarkPath(vgSpec.marks, intent.markName, []);
      if (!path) continue;
      const mark = path[path.length - 1];
      if (mark.type !== 'rect') continue;

      const enc = mark.encode?.update;
      if (!enc) continue;

      // Bars only for now. Bars and ticks both compile to rect marks, but VL
      // tags them differently via ariaRoleDescription ('bar' vs 'tick'). Skip
      // anything that is explicitly not a bar; allow rects with no role.
      const role = enc.ariaRoleDescription?.value;
      if (role && role !== 'bar') continue;

      // Stacked/rounded bars are wrapped in a facet "stack group" that is
      // clipped to the bar's bounding box. A label placed at the bar tip would
      // be clipped away, so drop the clip on any faceted ancestor — the label
      // (and only the label) then renders past the bar edge.
      for (let i = 0; i < path.length - 1; i++) {
        const g = path[i];
        if (g.from && g.from.facet && g.encode?.update?.clip) {
          g.encode.update.clip = { value: false };
        }
      }

      // Horizontal bars carry a height encoding (band on y); vertical bars
      // carry a width encoding (band on x). Holds for faceted marks too,
      // where the band size is {field: {group: ...}}.
      const isHBar = !!enc.height;
      const textEnc = {};

      // Resolve the displayed field from the mark's measure encoding (handles
      // VL aggregation renaming). Centered marks (tick/point) keep the field on
      // xc/yc, so fall back to those, then to the intent's declared field.
      // A stacked segment has distinct start/end fields on the measure axis.
      const mAxis = isHBar ? 'x' : 'y';
      const mRef = enc[mAxis] || enc[mAxis + 'c'];
      const bRef = enc[mAxis + '2'];
      const mField = mRef?.field;
      const bField = bRef?.field;
      const isStacked = !!(bField && mField && bField !== mField);

      if (isHBar) {
        const y = bandCenter(enc, 'y');
        if (y) textEnc.y = y;
        const hPos = intent.horizontal;
        const mid = hPos === 'center' && isStacked ? midSignal(enc, 'x') : null;
        if (mid) {
          // Inside the segment, horizontally centered between start and end.
          textEnc.x = { signal: mid };
          textEnc.align = { value: 'center' };
        } else if (hPos === 'left') {
          const x = measurePos(enc, 'x', false);
          if (x) textEnc.x = x;
          textEnc.align = { value: 'right' };
          textEnc.dx = { value: -4 };
        } else {
          const x = measurePos(enc, 'x', true);
          if (x) textEnc.x = x;
          textEnc.align = { value: 'left' };
          textEnc.dx = { value: 4 };
        }
        textEnc.baseline = { value: 'middle' };
      } else {
        const x = bandCenter(enc, 'x');
        if (x) textEnc.x = x;
        const vPos = intent.vertical;
        const mid = vPos === 'center' && isStacked ? midSignal(enc, 'y') : null;
        if (mid) {
          // Inside the segment, vertically centered between start and end.
          textEnc.y = { signal: mid };
          textEnc.baseline = { value: 'middle' };
        } else if (vPos === 'bottom') {
          const y = measurePos(enc, 'y', false);
          if (y) textEnc.y = y;
          textEnc.baseline = { value: 'top' };
          textEnc.dy = { value: 4 };
        } else {
          // top, or center on a non-stacked bar → just above the bar top.
          const y = measurePos(enc, 'y', true);
          if (y) textEnc.y = y;
          textEnc.baseline = { value: 'bottom' };
          textEnc.dy = { value: -4 };
        }
        textEnc.align = { value: 'center' };
      }

      if (intent.format) {
        const expr = isStacked
          ? "format(datum['" + mField + "'] - datum['" + bField + "'], '" + intent.format + "')"
          : "format(datum['" + (mField || intent.field) + "'], '" + intent.format + "')";
        textEnc.text = { signal: expr };
      } else if (isStacked) {
        textEnc.text = { signal: "datum['" + mField + "'] - datum['" + bField + "']" };
      } else {
        textEnc.text = { field: mField || intent.field };
      }

      textEnc.fontSize = { value: intent.size || 11 };
      if (intent.color === 'match' && enc.fill) {
        textEnc.fill = clone(enc.fill);
      } else {
        textEnc.fill = { value: intent.color || '#333333' };
      }

      // KAN-289: give the edge label room so it isn't clipped.
      const measureScaleName = (enc[mAxis] || enc[mAxis + 'c'])?.scale;
      if (measureScaleName) {
        if (isHBar) {
          const hSide = intent.horizontal || 'right';
          if (hSide !== 'center') {
            applyHeadroom(vgSpec, measureScaleName, HEADROOM.horizontal, hSide === 'right');
          }
        } else {
          const vSide = intent.vertical || 'top';
          if (vSide !== 'center') {
            applyHeadroom(vgSpec, measureScaleName, HEADROOM.vertical, vSide === 'top');
          }
        }
      }

      const textMark = {
        type: 'text',
        from: clone(mark.from),
        encode: { update: textEnc }
      };
      insertAfterMark(vgSpec.marks, mark, textMark);
    }
    return vgSpec;
  }

  global.charterPatch = charterPatch;
})(typeof window !== 'undefined' ? window : globalThis);
