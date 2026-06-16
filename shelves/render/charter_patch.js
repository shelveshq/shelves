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
  function findNamedMark(marks, name) {
    if (!marks) return null;
    for (const m of marks) {
      if (m.name === name || m.name === name + '_marks') return m;
      if (m.marks) {
        const found = findNamedMark(m.marks, name);
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

  function charterPatch(vgSpec) {
    const labels = vgSpec.usermeta?.charter?.labels;
    if (!labels || labels.length === 0) return vgSpec;

    for (const intent of labels) {
      const mark = findNamedMark(vgSpec.marks, intent.markName);
      if (!mark || mark.type !== 'rect') continue;

      const enc = mark.encode?.update;
      if (!enc) continue;

      const isHBar = !!enc.height;
      const textEnc = {};

      if (isHBar) {
        if (enc.y) {
          textEnc.y = JSON.parse(JSON.stringify(enc.y));
          // Compiled Vega puts the band width on a separate height signal;
          // the y ref is {scale, field} with no band key. Always center on
          // the band so the label sits over the bar, not its leading edge.
          textEnc.y.band = 0.5;
        }
        const hPos = intent.horizontal || 'center';
        if (hPos === 'left') {
          if (enc.x2) textEnc.x = JSON.parse(JSON.stringify(enc.x2));
          textEnc.align = { value: 'right' };
          textEnc.dx = { value: -4 };
        } else {
          if (enc.x) textEnc.x = JSON.parse(JSON.stringify(enc.x));
          textEnc.align = { value: 'left' };
          textEnc.dx = { value: 4 };
        }
        textEnc.baseline = { value: 'middle' };
      } else {
        if (enc.x) {
          textEnc.x = JSON.parse(JSON.stringify(enc.x));
          // Compiled Vega puts the band width on a separate width signal;
          // the x ref is {scale, field} with no band key. Always center on
          // the band so the label sits over the bar, not its leading edge.
          textEnc.x.band = 0.5;
        }
        const vPos = intent.vertical || 'center';
        if (vPos === 'bottom') {
          if (enc.y2) textEnc.y = JSON.parse(JSON.stringify(enc.y2));
          textEnc.baseline = { value: 'top' };
          textEnc.dy = { value: 4 };
        } else {
          if (enc.y) textEnc.y = JSON.parse(JSON.stringify(enc.y));
          textEnc.baseline = { value: 'bottom' };
          textEnc.dy = { value: -4 };
        }
        textEnc.align = { value: 'center' };
      }

      const mField = isHBar ? enc.x?.field : enc.y?.field;
      const bField = isHBar ? enc.x2?.field : enc.y2?.field;
      const isStacked = !!(bField && mField && bField !== mField);

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
        textEnc.fill = JSON.parse(JSON.stringify(enc.fill));
      } else {
        textEnc.fill = { value: intent.color || '#333333' };
      }

      const textMark = {
        type: 'text',
        from: JSON.parse(JSON.stringify(mark.from)),
        encode: { update: textEnc }
      };
      insertAfterMark(vgSpec.marks, mark, textMark);
    }
    return vgSpec;
  }

  global.charterPatch = charterPatch;
})(typeof window !== 'undefined' ? window : globalThis);
