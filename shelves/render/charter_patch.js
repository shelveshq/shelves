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

  // Map the user's preferred label side to an ordered list of Vega label-
  // transform anchor candidates: [primary, fallback]. The transform tries them
  // in order and hides the label (opacity 0) if none fit. 'center' → ['middle']
  // with no fallback, so a value that cannot fit inside its mark is hidden.
  function anchorCandidates(side) {
    switch (side) {
      case 'top':
        return ['top', 'bottom'];
      case 'bottom':
        return ['bottom', 'top'];
      case 'left':
        return ['left', 'right'];
      case 'right':
        return ['right', 'left'];
      case 'center':
        return ['middle'];
      default:
        return ['top', 'bottom'];
    }
  }

  // ── Deterministic inside-segment placement (stacked / explicit center) ──────
  // The Vega label transform reliably places OUTSIDE labels with collision
  // avoidance, but its `['middle']` anchor drops most stacked-segment labels
  // (only one category's segments survive). Inside a stacked bar every segment
  // should be labeled at its own midpoint — deterministically, not via the
  // collision solver. These helpers (sourced from the DATA, like a plain text
  // mark) compute that midpoint, mirroring the pre-transform placement.

  // Center of the band along the cross axis ('x' or 'y'). Plain bars carry the
  // band ref on the rect ({scale, field}); add band: 0.5 to center on the band.
  // Faceted bars fill their parent facet group and carry no band ref — center
  // inside the group via {field: {group: size}, mult: 0.5}.
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

  // Pixel-position expression for a measure-axis value ref, for use in signals.
  function posExpr(ref) {
    if (!ref) return null;
    if (ref.scale && ref.field) return "scale('" + ref.scale + "', datum['" + ref.field + "'])";
    if (ref.scale && 'value' in ref) return "scale('" + ref.scale + "', " + ref.value + ")";
    if (ref.signal) return '(' + ref.signal + ')';
    if ('value' in ref) return '' + ref.value;
    return null;
  }

  // Signal for the pixel midpoint of a stacked segment along the measure axis
  // ('x' or 'y') — halfway between its value-end (axis) and value-start (axis2).
  function midSignal(enc, axis) {
    const a = posExpr(enc[axis]);
    const b = posExpr(enc[axis + '2']);
    return a && b ? '(' + a + ' + ' + b + ') / 2' : null;
  }

  // Pixel-dimension expression for a group's width/height encode ref.
  function dimExpr(ref) {
    if (!ref) return null;
    if (ref.signal) return ref.signal;
    if (typeof ref.value === 'number') return String(ref.value);
    return null;
  }

  // The [w, h] signal the label transform lays labels out within. In a single
  // unit spec the rect is top-level and the global `width`/`height` signals are
  // correct. In concat/faceted layouts there is NO top-level `width`/`height`
  // signal — the enclosing child group carries its own size (e.g.
  // `childWidth`/`mark_0_height`), so `[width, height]` resolves to 0 and the
  // transform throws. Walk up to the nearest non-facet ancestor group that
  // declares explicit dimensions; fall back to the top-level signals.
  function labelSizeSignal(path) {
    for (let i = path.length - 2; i >= 0; i--) {
      const g = path[i];
      if (g.from && g.from.facet) continue; // facet cell — sized to one datum
      const genc = g.encode && g.encode.update;
      if (!genc) continue;
      const w = dimExpr(genc.width);
      const h = dimExpr(genc.height);
      if (w && h) return '[' + w + ', ' + h + ']';
    }
    return '[width, height]';
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

      // Stacked/rounded bars are wrapped in a facet "stack group" clipped to the
      // bar's bounding box. A label placed past the bar tip would be clipped
      // away, so drop the clip on any faceted ancestor.
      for (let i = 0; i < path.length - 1; i++) {
        const g = path[i];
        if (g.from && g.from.facet && g.encode?.update?.clip) {
          g.encode.update.clip = { value: false };
        }
      }

      // Orientation + measure fields, read from the bar's measure encoding.
      // Horizontal bars carry a height encoding (band on y); vertical bars a
      // width encoding (band on x). Tick/point marks center on xc/yc.
      const isHBar = !!enc.height;
      const mAxis = isHBar ? 'x' : 'y';
      const mRef = enc[mAxis] || enc[mAxis + 'c'];
      const bRef = enc[mAxis + '2'];
      const mField = mRef?.field;
      const bField = bRef?.field;
      // VL stack-encodes every bar (distinct start/end fields), so this is true
      // for single bars too; the segment value end - start is correct because a
      // single bar's start is 0.
      const isStacked = !!(bField && mField && bField !== mField);

      // A real multi-segment stack carries a fill bound to a field DIFFERENT
      // from the band/category field (e.g. cols:category + color:sub_category).
      // A single bar merely colored by its own category has fill.field ===
      // bandField. Charter has no grouped (xOffset) bars, so fill≠band ⟹ stack.
      // Stacked segments default to inside-center: an outside top/right anchor
      // only fits the outermost segment, so the inner ones would be auto-hidden.
      const bandField = (enc[isHBar ? 'y' : 'x'] || {}).field;
      const isSegmented = !!(enc.fill && enc.fill.field && bandField && enc.fill.field !== bandField);

      // Preferred side → anchor candidates. Unset side → outside default for a
      // plain bar, inside-center for a stacked segment.
      const outsideDefault = isHBar ? 'right' : 'top';
      const side = (isHBar ? intent.horizontal : intent.vertical)
        || (isSegmented ? 'center' : outsideDefault);
      const isCenter = side === 'center';

      // Inside (center) and outside placement read the measure value
      // differently because they are sourced differently (see below): an outside
      // label is sourced FROM the bar mark, so its tuple is at datum.datum; an
      // inside label is sourced from the DATA, so its tuple is datum directly.
      const tuple = isCenter ? 'datum' : 'datum.datum';
      const seg = isStacked
        ? tuple + "['" + mField + "'] - " + tuple + "['" + bField + "']"
        : tuple + "['" + (mField || intent.field) + "']";
      const textSignal = intent.format
        ? "format(" + seg + ", '" + intent.format + "')"
        : seg;

      const textEnc = {
        text: { signal: textSignal },
        fontSize: { value: intent.size || 11 },
      };
      if (intent.color === 'match' && enc.fill && enc.fill.scale && enc.fill.field) {
        // Re-resolve the color scale against the source datum's category field.
        // (Sourced-from-mark needs the datum. prefix; sourced-from-data does not.)
        const fillField = (isCenter ? '' : 'datum.') + enc.fill.field;
        textEnc.fill = { scale: enc.fill.scale, field: fillField };
      } else {
        textEnc.fill = { value: intent.color || '#333333' };
      }

      let textMark;
      if (isCenter) {
        // Inside placement: deterministically center the value in its segment.
        // The Vega label transform's ['middle'] anchor drops most stacked
        // labels, so place by hand (cross-axis band center + measure midpoint)
        // and source from the DATA, like an ordinary text mark.
        const cross = bandCenter(enc, isHBar ? 'y' : 'x');
        if (cross) textEnc[isHBar ? 'y' : 'x'] = cross;
        const mid = midSignal(enc, mAxis);
        if (mid) textEnc[mAxis] = { signal: mid };
        textEnc.align = { value: 'center' };
        textEnc.baseline = { value: 'middle' };
        textMark = {
          type: 'text',
          from: clone(mark.from),
          encode: { update: textEnc },
        };
      } else {
        // Outside placement: delegate to the Vega label transform for collision
        // avoidance (preferred anchor → opposite fallback → hide). Source FROM
        // the bar mark so the transform can read each bar's bounding box.
        const measureScaleName = mRef?.scale;
        if (measureScaleName) {
          // KAN-289: give the edge label room so it isn't clipped and the
          // preferred outside anchor fits instead of flipping inside.
          applyHeadroom(
            vgSpec,
            measureScaleName,
            isHBar ? HEADROOM.horizontal : HEADROOM.vertical,
            isHBar ? side === 'right' : side === 'top',
          );
        }
        textMark = {
          type: 'text',
          from: { data: mark.name },
          encode: { update: textEnc },
          transform: [{
            type: 'label',
            size: { signal: labelSizeSignal(path) },
            avoidBaseMark: true,
            anchor: anchorCandidates(side),
            offset: [3],
            as: ['x', 'y', 'opacity', 'align', 'baseline'],
          }],
        };
      }
      insertAfterMark(vgSpec.marks, mark, textMark);
    }
    return vgSpec;
  }

  global.charterPatch = charterPatch;
})(typeof window !== 'undefined' ? window : globalThis);
