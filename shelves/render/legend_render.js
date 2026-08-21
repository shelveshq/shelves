// legend_render.js — browser-side rendering for INDEPENDENT dashboard legends.
//
// SHE-10 bakes data-source/data-channel/data-orientation/data-title onto each
// legend placeholder div. After a sheet's Vega view embeds, `populate` finds the
// legend divs bound to that sheet, resolves the live scale from the channel
// (SHE-28 — Python no longer emits a compile-time scale name), and renders
// swatch/label content. Split like label_patch.js / compound_fit.js: Python owns
// intent (the channel + title + orientation as data attributes); JS owns
// mechanics (resolve the scale, build markup). Authored as a plain global so it
// works inlined into a
// file:// page and require()d by `node --test`. The markup core (buildMarkup /
// renderLegend / renderCategorical) is DOM-free and unit-tested with node.
//
// SHE-11 implements ONLY the categorical (ordinal/point/band) branch. Gradient
// (quantitative color) and size legends fall through to empty markup — added by
// follow-up stories with no change to this plumbing.
(function (global) {
  'use strict';

  // Styling reads the SHE-85 `--shelves-legend-*` theme tokens (emitted by
  // layout.py on any dashboard with legends), each with a CSS var() fallback
  // equal to the historical hardcoded value — so the JS still renders correctly
  // standalone (under `node --test` and in a page without the vars) with zero
  // visual change under the default theme. Labels inherit the page body font.
  var SWATCH_STYLE =
    'display:inline-block;width:var(--shelves-legend-swatch-size,12px);' +
    'height:var(--shelves-legend-swatch-size,12px);' +
    'border-radius:var(--shelves-legend-swatch-radius,2px);' +
    'margin-right:6px;flex:0 0 auto';
  var LABEL_STYLE =
    'font-size:var(--shelves-legend-font-size,12px);line-height:1.4;white-space:nowrap';
  var TITLE_STYLE =
    'font-size:var(--shelves-legend-font-size,12px);' +
    'font-weight:var(--shelves-legend-title-weight,600);margin-bottom:6px';
  var ROW_STYLE = 'display:flex;align-items:center';
  var ITEMS_STYLE_V = 'display:flex;flex-direction:column;gap:var(--shelves-legend-gap,4px)';
  var ITEMS_STYLE_H =
    'display:flex;flex-direction:row;flex-wrap:wrap;gap:var(--shelves-legend-gap-horizontal,12px)';

  // SHE-12 gradient styling. Bar rounding shares the swatch-radius token.
  var GRADIENT_STOPS = 16; // n+1 color samples across the domain
  var GRADIENT_BAR_V =
    'width:14px;height:120px;border-radius:var(--shelves-legend-swatch-radius,2px);flex:0 0 auto';
  // Horizontal bar fills the container width so it aligns with the tick row,
  // which spans the full width via space-between (SHE-12 alignment fix).
  var GRADIENT_BAR_H =
    'height:14px;width:100%;border-radius:var(--shelves-legend-swatch-radius,2px);flex:0 0 auto';
  var GRADIENT_WRAP_V = 'display:flex;flex-direction:row;gap:6px;align-items:stretch';
  var GRADIENT_WRAP_H = 'display:flex;flex-direction:column;gap:4px';
  var GRADIENT_TICKS_V = 'display:flex;flex-direction:column;justify-content:space-between';
  var GRADIENT_TICKS_H = 'display:flex;flex-direction:row;justify-content:space-between';

  // SHE-13 size legend styling (no dedicated theme tokens yet).
  var SIZE_TICKS = 5; // representative domain stops (mirrors Vega's ~5 default ticks)
  // Neutral fill: a size legend encodes magnitude, not colour (the chart may also
  // colour-encode a different field, so a coloured glyph would mislead).
  var SIZE_GLYPH_FILL = '#888';
  var SIZE_ITEMS_STYLE_V = 'display:flex;flex-direction:column;gap:6px';
  var SIZE_ITEMS_STYLE_H =
    'display:flex;flex-direction:row;flex-wrap:wrap;gap:14px;align-items:flex-end';

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

  // Pure: the shared legend heading. '' for a falsy title (so callers can push
  // it unconditionally). One source for all three builders (categorical/
  // gradient/size) so a markup or a11y change lands in exactly one place.
  function titleMarkup(title) {
    return title
      ? '<div class="legend-title" style="' + TITLE_STYLE + '">' + escapeHtml(title) + '</div>'
      : '';
  }

  // Pure: true when `dom` is a usable continuous domain — >= 2 entries with
  // numeric endpoints. Shared by the gradient and size renderers (any new
  // continuous legend type guards through here too).
  function isContinuousDomain(dom) {
    return (
      dom.length >= 2 &&
      typeof dom[0] === 'number' &&
      typeof dom[dom.length - 1] === 'number'
    );
  }

  // Pure: entries = [{label, color}], opts = {title, orientation}. Returns an
  // HTML string. Colors come from the trusted Vega scale and are emitted into a
  // style attribute as-is; label/title text is escaped.
  function buildMarkup(entries, opts) {
    opts = opts || {};
    var horizontal = opts.orientation === 'horizontal';
    var itemsStyle = horizontal ? ITEMS_STYLE_H : ITEMS_STYLE_V;
    var parts = [];
    if (opts.title) parts.push(titleMarkup(opts.title));
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
    if (opts.title) parts.push(titleMarkup(opts.title));
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
    if (!isContinuousDomain(dom)) return '';
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

  // Pure: a symbol's AREA in px² (what a Vega `size` scale yields) -> its pixel
  // DIAMETER. Vega encodes `size` as area, so a circle of area A has diameter
  // 2*sqrt(A/π). Guards non-positive / non-numeric input to 0 (invisible glyph;
  // its label still renders) so a zero-baseline domain never produces NaN.
  function areaToDiameter(area) {
    if (typeof area !== 'number' || !(area > 0)) return 0;
    return 2 * Math.sqrt(area / Math.PI);
  }

  // Representative domain values for the glyph stops. Prefers the scale's own nice
  // tick values (real Vega continuous scales expose .ticks(count)); falls back to
  // `count` evenly-spaced values across the domain (endpoints inclusive) for fake
  // scales or scales without .ticks. Always returns >= 2 ascending values.
  function sizeTicks(scale, count) {
    count = count || SIZE_TICKS;
    if (scale && typeof scale.ticks === 'function') {
      try {
        var t = scale.ticks(count);
        if (t && t.length >= 2) return t;
      } catch (e) {
        /* fall through to evenly-spaced */
      }
    }
    var dom = scale.domain();
    var lo = dom[0];
    var hi = dom[dom.length - 1];
    var out = [];
    for (var i = 0; i < count; i++) {
      out.push(lo + ((hi - lo) * i) / (count - 1));
    }
    return out;
  }

  // Pure: tick values -> [{value, diameter}] via the live scale
  // (value -> area -> diameter). Preserves tick order (ascending: smallest first).
  function sizeEntries(scale, values) {
    return values.map(function (v) {
      return { value: v, diameter: areaToDiameter(scale(v)) };
    });
  }

  // Pure: entries = [{label, diameter}], opts = {title, orientation, maxDiameter}.
  // Renders a graduated-glyph list. Each glyph sits in a fixed maxDiameter×
  // maxDiameter cell so labels align in a column (vertical) and circles share a
  // baseline (horizontal). Colours come from a trusted constant; label text is
  // escaped. Returns an HTML string.
  function buildSizeMarkup(entries, opts) {
    opts = opts || {};
    var horizontal = opts.orientation === 'horizontal';
    var itemsStyle = horizontal ? SIZE_ITEMS_STYLE_H : SIZE_ITEMS_STYLE_V;
    var maxD = opts.maxDiameter || 0;
    var parts = [];
    if (opts.title) parts.push(titleMarkup(opts.title));
    var rows = (entries || []).map(function (e) {
      var cell =
        'display:inline-flex;justify-content:center;align-items:center;' +
        'width:' + maxD + 'px;height:' + maxD + 'px;margin-right:6px;flex:0 0 auto';
      var circle =
        'display:inline-block;border-radius:50%;background:' + SIZE_GLYPH_FILL +
        ';width:' + e.diameter + 'px;height:' + e.diameter + 'px';
      return (
        '<div class="legend-item" style="' + ROW_STYLE + '">' +
        '<span class="legend-size-glyph" style="' + cell + '">' +
          '<span style="' + circle + '"></span>' +
        '</span>' +
        '<span class="legend-label" style="' + LABEL_STYLE + '">' +
          escapeHtml(e.label) +
          '</span>' +
        '</div>'
      );
    });
    parts.push(
      '<div class="legend-items" style="' + itemsStyle + '">' + rows.join('') + '</div>'
    );
    return parts.join('');
  }

  // A continuous size scale -> graduated-glyph markup. Returns '' for a non-numeric
  // or degenerate (<2 entry) domain (caller warns -> empty box, never a throw).
  function renderSize(scale, opts) {
    opts = opts || {};
    var dom = scale && scale.domain ? scale.domain() : [];
    if (!isContinuousDomain(dom)) return '';
    var values = sizeTicks(scale, SIZE_TICKS);
    var entries = sizeEntries(scale, values);
    var fmt = makeFormatter(opts.format);
    var labeled = entries.map(function (e) {
      return { label: fmt(e.value), diameter: e.diameter };
    });
    var maxD = labeled.reduce(function (m, e) {
      return e.diameter > m ? e.diameter : m;
    }, 0);
    return buildSizeMarkup(labeled, {
      title: opts.title,
      orientation: opts.orientation,
      maxDiameter: maxD,
    });
  }

  // Dispatch on scale + channel. Categorical (any channel) -> swatches.
  // Continuous color -> gradient (SHE-12). Continuous size -> graduated glyphs
  // (SHE-13). Shape (SHE-14) and channel-less continuous scales return ''
  // (graceful, no throw).
  function renderLegend(scale, opts) {
    opts = opts || {};
    if (!scale || typeof scale.type !== 'string') return '';
    if (CATEGORICAL_TYPES[scale.type]) return renderCategorical(scale, opts);
    if (opts.channel === 'color') return renderGradient(scale, opts);
    if (opts.channel === 'size') return renderSize(scale, opts);
    return '';
  }

  function warn(msg) {
    if (typeof console !== 'undefined' && console.warn) console.warn(msg);
  }

  // Resolve the live Vega scale for a legend from its CHANNEL, never throwing.
  // SHE-28: the channel is the source of truth — Python no longer guesses the
  // compiled scale name. Primary: the public `view.scale(channel)` (a single-view
  // spec names its scale exactly `<channel>`). Fallback: scan the live view's
  // scale names for one ending in `_<channel>` (e.g. `mark_0_color`), which is the
  // namespaced name Vega-Lite produces when a unit spec carries a `name` (labeled
  // charts). `view._runtime.scales` is the (internal) enumeration; there is no
  // public scale-name enumeration API, so it is used for the scan only.
  // Returns the scale object or null.
  function resolveScale(view, channel) {
    if (!view || !channel) return null;
    try {
      return view.scale(channel);
    } catch (e) {
      /* labeled chart: scale is namespaced; fall to the suffix scan */
    }
    if (view._runtime && view._runtime.scales) {
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
      var channel = div.getAttribute('data-channel');
      if (!channel) return;
      var scale = resolveScale(view, channel);
      if (!scale) {
        warn(
          'legend: could not resolve a scale for channel ' +
            JSON.stringify(channel) + ' on ' + sheetId
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
    titleMarkup: titleMarkup,
    isContinuousDomain: isContinuousDomain,
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
    // SHE-13:
    areaToDiameter: areaToDiameter,
    sizeTicks: sizeTicks,
    sizeEntries: sizeEntries,
    buildSizeMarkup: buildSizeMarkup,
    renderSize: renderSize,
  };

  global.legendRender = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
