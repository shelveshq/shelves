// legend_render.js — browser-side rendering for INDEPENDENT dashboard legends.
//
// SHE-10 bakes data-source/data-scale/data-orientation/data-title onto each
// legend placeholder div. After a sheet's Vega view embeds, `populate` finds the
// legend divs bound to that sheet, reads the live scale, and renders swatch/label
// content. Split like label_patch.js / compound_fit.js: Python owns intent (the
// link + title + orientation as data attributes); JS owns mechanics (read the
// scale, build markup). Authored as a plain global so it works inlined into a
// file:// page and require()d by `node --test`. The markup core (buildMarkup /
// renderLegend / renderCategorical) is DOM-free and unit-tested with node.
//
// SHE-11 implements ONLY the categorical (ordinal/point/band) branch. Gradient
// (quantitative color) and size legends fall through to empty markup — added by
// follow-up stories with no change to this plumbing.
(function (global) {
  'use strict';

  // Static styling. No dedicated legend layout tokens exist in the theme yet, so
  // these are reasonable inline defaults; labels inherit the page body font.
  var SWATCH_STYLE =
    'display:inline-block;width:12px;height:12px;border-radius:2px;' +
    'margin-right:6px;flex:0 0 auto';
  var LABEL_STYLE = 'font-size:12px;line-height:1.4;white-space:nowrap';
  var TITLE_STYLE = 'font-size:12px;font-weight:600;margin-bottom:6px';
  var ROW_STYLE = 'display:flex;align-items:center';
  var ITEMS_STYLE_V = 'display:flex;flex-direction:column;gap:4px';
  var ITEMS_STYLE_H = 'display:flex;flex-direction:row;flex-wrap:wrap;gap:12px';

  // Categorical scale types this renderer handles. Others (linear/pow/sqrt/
  // sequential/...) return empty markup until their renderers land.
  var CATEGORICAL_TYPES = { ordinal: true, point: true, band: true };

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Pure: entries = [{label, color}], opts = {title, orientation}. Returns an
  // HTML string. Colors come from the trusted Vega scale and are emitted into a
  // style attribute as-is; label/title text is escaped.
  function buildMarkup(entries, opts) {
    opts = opts || {};
    var horizontal = opts.orientation === 'horizontal';
    var itemsStyle = horizontal ? ITEMS_STYLE_H : ITEMS_STYLE_V;
    var parts = [];
    if (opts.title) {
      parts.push(
        '<div class="legend-title" style="' + TITLE_STYLE + '">' +
          escapeHtml(opts.title) +
          '</div>'
      );
    }
    var rows = (entries || []).map(function (e) {
      return (
        '<div class="legend-item" style="' + ROW_STYLE + '">' +
        '<span class="legend-swatch" style="' + SWATCH_STYLE +
          ';background:' + e.color + '"></span>' +
        '<span class="legend-label" style="' + LABEL_STYLE + '">' +
          escapeHtml(e.label) +
          '</span>' +
        '</div>'
      );
    });
    parts.push(
      '<div class="legend-items" style="' + itemsStyle + '">' +
        rows.join('') +
        '</div>'
    );
    return parts.join('');
  }

  // Pure: a live ordinal/point/band scale -> categorical markup.
  function renderCategorical(scale, opts) {
    var domain = scale && scale.domain ? scale.domain() : [];
    var entries = domain.map(function (v) {
      return { label: v, color: scale(v) };
    });
    return buildMarkup(entries, opts);
  }

  // Pure dispatch on scale.type. Only categorical implemented; everything else
  // returns '' (graceful, no throw).
  function renderLegend(scale, opts) {
    if (!scale || typeof scale.type !== 'string') return '';
    if (CATEGORICAL_TYPES[scale.type]) return renderCategorical(scale, opts);
    return '';
  }

  // Browser-only: fill every legend div bound to `sheetId` from `view`'s scales.
  function populate(view, sheetId, doc) {
    doc = doc || (typeof document !== 'undefined' ? document : null);
    if (!doc || !view) return;
    var divs = doc.querySelectorAll('div[data-source="' + sheetId + '"]');
    Array.prototype.forEach.call(divs, function (div) {
      var scaleName = div.getAttribute('data-scale');
      if (!scaleName) return;
      var scale;
      try {
        scale = view.scale(scaleName);
      } catch (e) {
        return; // scale not present on this view → leave the box empty
      }
      div.innerHTML = renderLegend(scale, {
        title: div.getAttribute('data-title') || '',
        orientation: div.getAttribute('data-orientation') || 'vertical',
      });
    });
  }

  var api = {
    escapeHtml: escapeHtml,
    buildMarkup: buildMarkup,
    renderCategorical: renderCategorical,
    renderLegend: renderLegend,
    populate: populate,
    CATEGORICAL_TYPES: CATEGORICAL_TYPES,
  };

  global.legendRender = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
