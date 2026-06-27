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

  // SHE-12 gradient styling (no dedicated theme tokens yet).
  var GRADIENT_STOPS = 16; // n+1 color samples across the domain
  var GRADIENT_BAR_V = 'width:14px;height:120px;border-radius:2px;flex:0 0 auto';
  // Horizontal bar fills the container width so it aligns with the tick row,
  // which spans the full width via space-between (SHE-12 alignment fix).
  var GRADIENT_BAR_H = 'height:14px;width:100%;border-radius:2px;flex:0 0 auto';
  var GRADIENT_WRAP_V = 'display:flex;flex-direction:row;gap:6px;align-items:stretch';
  var GRADIENT_WRAP_H = 'display:flex;flex-direction:column;gap:4px';
  var GRADIENT_TICKS_V = 'display:flex;flex-direction:column;justify-content:space-between';
  var GRADIENT_TICKS_H = 'display:flex;flex-direction:row;justify-content:space-between';

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

  // Build a number formatter from a d3 spec, using vega's locale when the page
  // has loaded vega (the embed script does). Falls back to String() under node
  // tests or when no spec is given. (vega.format / vega.numberFormat are NOT
  // formatters — the formatter is vega.formatLocale().format(spec).)
  function makeFormatter(spec) {
    if (spec && global.vega && global.vega.formatLocale) {
      try {
        return global.vega.formatLocale().format(spec);
      } catch (e) {
        /* fall through to String */
      }
    }
    return function (v) {
      return String(v);
    };
  }

  // Pure: domain -> [min, mid, max] tick values (first & last domain entries).
  function gradientTicks(domain) {
    var lo = domain[0];
    var hi = domain[domain.length - 1];
    return [lo, (lo + hi) / 2, hi];
  }

  // Pure: n+1 evenly-spaced color stops across [min, max]. offset in [0, 1].
  function gradientStops(scale, n) {
    n = n || GRADIENT_STOPS;
    var dom = scale.domain();
    var lo = dom[0];
    var hi = dom[dom.length - 1];
    var out = [];
    for (var i = 0; i <= n; i++) {
      var t = i / n;
      out.push({ offset: t, color: scale(lo + t * (hi - lo)) });
    }
    return out;
  }

  // Pure: stops + CSS direction -> "linear-gradient(dir, color pct%, ...)".
  function gradientCss(stops, direction) {
    var parts = stops.map(function (s) {
      return s.color + ' ' + s.offset * 100 + '%';
    });
    return 'linear-gradient(' + direction + ', ' + parts.join(', ') + ')';
  }

  // Pure: assemble gradient legend markup. `ticks` is the display-ordered list of
  // already-formatted label strings; `css` is the linear-gradient background.
  function buildGradientMarkup(opts) {
    opts = opts || {};
    var horizontal = opts.orientation === 'horizontal';
    var parts = [];
    if (opts.title) {
      parts.push(
        '<div class="legend-title" style="' + TITLE_STYLE + '">' +
          escapeHtml(opts.title) +
          '</div>'
      );
    }
    var bar =
      '<div class="legend-gradient-bar" style="' +
      (horizontal ? GRADIENT_BAR_H : GRADIENT_BAR_V) +
      ';background:' + opts.css + '"></div>';
    var tickSpans = (opts.ticks || []).map(function (t) {
      return '<span class="legend-label" style="' + LABEL_STYLE + '">' + escapeHtml(t) + '</span>';
    });
    var ticks =
      '<div class="legend-gradient-ticks" style="' +
      (horizontal ? GRADIENT_TICKS_H : GRADIENT_TICKS_V) +
      '">' + tickSpans.join('') + '</div>';
    parts.push(
      '<div class="legend-gradient" style="' +
        (horizontal ? GRADIENT_WRAP_H : GRADIENT_WRAP_V) +
        '">' + bar + ticks + '</div>'
    );
    return parts.join('');
  }

  // A continuous color scale -> gradient markup. Returns '' for a non-numeric or
  // degenerate (<2 entry) domain (caller warns -> empty box, never a throw).
  function renderGradient(scale, opts) {
    opts = opts || {};
    var dom = scale && scale.domain ? scale.domain() : [];
    if (dom.length < 2 || typeof dom[0] !== 'number' || typeof dom[dom.length - 1] !== 'number') {
      return '';
    }
    var horizontal = opts.orientation === 'horizontal';
    var css = gradientCss(gradientStops(scale, GRADIENT_STOPS), horizontal ? 'to right' : 'to top');
    var fmt = makeFormatter(opts.format);
    var labels = gradientTicks(dom).map(fmt); // [min, mid, max]
    // vertical bar shows max at top; horizontal shows min at left.
    var display = horizontal ? labels : labels.slice().reverse();
    return buildGradientMarkup({
      css: css,
      ticks: display,
      orientation: opts.orientation,
      title: opts.title,
    });
  }

  // Dispatch on scale + channel. Categorical (any channel) -> swatches.
  // Continuous color -> gradient (SHE-12). Size (SHE-13), shape (SHE-14), and
  // channel-less continuous scales return '' (graceful, no throw).
  function renderLegend(scale, opts) {
    opts = opts || {};
    if (!scale || typeof scale.type !== 'string') return '';
    if (CATEGORICAL_TYPES[scale.type]) return renderCategorical(scale, opts);
    if (opts.channel === 'color') return renderGradient(scale, opts);
    return '';
  }

  function warn(msg) {
    if (typeof console !== 'undefined' && console.warn) console.warn(msg);
  }

  // Resolve the live Vega scale for a legend, never throwing. Primary lookup is
  // the exact name Python emitted (data-scale). Fallback: scan the view's scale
  // names for one matching the channel — `name === channel` or `name` ending in
  // `_<channel>`. This recovers the namespaced scale (e.g. `mark_0_color`) that
  // Vega-Lite produces when a unit spec carries a `name` (labeled charts), so the
  // legend is robust even if the compile-time scale name is wrong or stale.
  // Returns the scale object or null.
  function resolveScale(view, scaleName, channel) {
    if (view && scaleName) {
      try {
        return view.scale(scaleName);
      } catch (e) {
        /* fall through to the channel scan */
      }
    }
    if (view && channel && view._runtime && view._runtime.scales) {
      var names = Object.keys(view._runtime.scales);
      var suffix = '_' + channel;
      for (var i = 0; i < names.length; i++) {
        var n = names[i];
        if (n === channel || (n.length > suffix.length && n.slice(-suffix.length) === suffix)) {
          try {
            return view.scale(n);
          } catch (e) {
            /* keep scanning */
          }
        }
      }
    }
    return null;
  }

  // Browser-only: fill every legend div bound to `sheetId` from `view`'s scales.
  // Failures warn rather than silently leaving an empty box (an unexplained empty
  // legend was a real debugging trap): an unresolvable scale and a resolved-but-
  // unrenderable scale (e.g. a not-yet-supported gradient/size type) each warn.
  function populate(view, sheetId, doc) {
    doc = doc || (typeof document !== 'undefined' ? document : null);
    if (!doc || !view) return;
    var divs = doc.querySelectorAll('div[data-source="' + sheetId + '"]');
    Array.prototype.forEach.call(divs, function (div) {
      var scaleName = div.getAttribute('data-scale');
      var channel = div.getAttribute('data-channel');
      if (!scaleName && !channel) return;
      var scale = resolveScale(view, scaleName, channel);
      if (!scale) {
        warn(
          'legend: could not resolve scale ' + JSON.stringify(scaleName) +
            ' (channel ' + JSON.stringify(channel) + ') on ' + sheetId
        );
        return;
      }
      var markup = renderLegend(scale, {
        title: div.getAttribute('data-title') || '',
        orientation: div.getAttribute('data-orientation') || 'vertical',
        channel: channel,
        format: div.getAttribute('data-format') || '',
      });
      if (!markup) {
        warn(
          'legend: scale type ' + JSON.stringify(scale.type) + ' on ' + sheetId +
            ' produced no content (unsupported legend type)'
        );
        return;
      }
      div.innerHTML = markup;
    });
  }

  var api = {
    escapeHtml: escapeHtml,
    buildMarkup: buildMarkup,
    renderCategorical: renderCategorical,
    resolveScale: resolveScale,
    renderLegend: renderLegend,
    populate: populate,
    // SHE-12:
    makeFormatter: makeFormatter,
    gradientTicks: gradientTicks,
    gradientStops: gradientStops,
    gradientCss: gradientCss,
    buildGradientMarkup: buildGradientMarkup,
    renderGradient: renderGradient,
    CATEGORICAL_TYPES: CATEGORICAL_TYPES,
  };

  global.legendRender = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
