// control_render.js — browser-side rendering for dashboard parameter and filter controls.
//
// Shared by parameters (data-param) and filters (data-type="filter").
// In Studio, controls post messages to the parent frame for recompile.
// In exported HTML, controls render as static value displays.
//
// Follows the legend_render.js pattern: IIFE, plain global
// (window.controlRender), pure markup functions + browser-only wiring.
(function (global) {
  'use strict';

  function escapeAttr(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Input-like widgets read the control token set by default, or the filter
  // token set (`--shelves-filter-*`, from the `layout.filter` theme block) when
  // the widget belongs to a filter control. `p` is the var-name prefix.
  function _labelStyle(p) {
    return 'font-size:var(--shelves-' + p + '-font-size,13px);' +
      'font-weight:500;margin-bottom:4px;white-space:nowrap;' +
      'color:var(--shelves-' + p + '-text,#1a1a1a)';
  }
  function _inputStyle(p) {
    return 'font-size:var(--shelves-' + p + '-font-size,13px);' +
      'height:var(--shelves-' + p + '-height,32px);' +
      'border:1px solid var(--shelves-' + p + '-border,#e5e7eb);' +
      'border-radius:var(--shelves-' + p + '-radius,4px);' +
      'background:var(--shelves-' + p + '-surface,#ffffff);' +
      'color:var(--shelves-' + p + '-text,#1a1a1a);' +
      'padding:0 8px;box-sizing:border-box;width:100%';
  }
  var LABEL_STYLE = _labelStyle('control');
  var FILTER_LABEL_STYLE = _labelStyle('filter');
  var INPUT_STYLE = _inputStyle('control');
  var FILTER_INPUT_STYLE = _inputStyle('filter');
  var WRAP_STYLE = 'display:flex;flex-direction:column';
  // Open-list widgets (dropdown:false) fill the height their box gives them and
  // scroll internally, so a long option list stays contained instead of bleeding
  // over neighbouring components. These are filter-only, so they read the filter
  // token set.
  var LIST_WRAP_STYLE = 'display:flex;flex-direction:column;height:100%;min-height:0';
  var LIST_BOX_STYLE = 'border:1px solid var(--shelves-filter-border,#e5e7eb);' +
    'border-radius:var(--shelves-filter-radius,4px);' +
    'background:var(--shelves-filter-surface,#ffffff);' +
    'padding:4px 8px;flex:1 1 auto;min-height:0;overflow-y:auto';
  var LIST_ITEM_STYLE = 'display:block;padding:2px 0;font-size:var(--shelves-filter-font-size,13px)';
  var LIST_ITEM_ALL_STYLE = LIST_ITEM_STYLE + ';font-weight:500';
  // Native <select multiple> as a scrollable listbox (dropdown:true for multi
  // mode). Height comes from the option `size` attribute (a few rows) — a
  // one-row-tall fixed height clips its own options with no scroll affordance.
  var NATIVE_MULTI_STYLE = 'font-size:var(--shelves-filter-font-size,13px);' +
    'border:1px solid var(--shelves-filter-border,#e5e7eb);' +
    'border-radius:var(--shelves-filter-radius,4px);' +
    'background:var(--shelves-filter-surface,#ffffff);' +
    'padding:2px 4px;box-sizing:border-box;width:100%;max-height:100%;overflow-y:auto';
  var STATIC_VALUE_STYLE = 'font-size:var(--shelves-control-font-size,13px);' +
    'color:var(--shelves-control-accent,#4A90D9)';
  var FILTER_STATIC_VALUE_STYLE = 'font-size:var(--shelves-filter-font-size,13px);' +
    'color:var(--shelves-filter-accent,#4A90D9)';

  function titleMarkup(title, isFilter) {
    if (!title) return '';
    var style = isFilter ? FILTER_LABEL_STYLE : LABEL_STYLE;
    return '<label style="' + style + '">' + escapeAttr(title) + '</label>';
  }

  function _parseOptions(options) {
    if (typeof options === 'string') {
      try { options = JSON.parse(options); } catch (e) { options = []; }
    }
    return options || [];
  }

  function buildDropdown(opts) {
    opts = opts || {};
    var options = _parseOptions(opts.options);
    var isFilter = opts.type === 'filter';
    var inputStyle = isFilter ? FILTER_INPUT_STYLE : INPUT_STYLE;
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, isFilter));
    parts.push('<select data-param="' + escapeAttr(opts.param || opts.field) + '" style="' + inputStyle + '">');
    if (isFilter) {
      var allSel = (opts.default == null) ? ' selected' : '';
      parts.push('<option value=""' + allSel + '>All</option>');
    }
    for (var i = 0; i < options.length; i++) {
      var o = options[i];
      var sel = (opts.default != null && String(o.value) === String(opts.default)) ? ' selected' : '';
      parts.push('<option value="' + escapeAttr(o.value) + '"' + sel + '>' +
        escapeAttr(o.label) + '</option>');
    }
    parts.push('</select>');
    parts.push('</div>');
    return parts.join('');
  }

  function buildStepper(opts) {
    opts = opts || {};
    var isFilter = opts.type === 'filter';
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, isFilter));
    parts.push('<input type="number"' +
      ' data-param="' + escapeAttr(opts.param || opts.field) + '"' +
      ' style="' + (isFilter ? FILTER_INPUT_STYLE : INPUT_STYLE) + '"' +
      ' value="' + escapeAttr(opts.default) + '"' +
      (opts.min != null ? ' min="' + escapeAttr(opts.min) + '"' : '') +
      (opts.max != null ? ' max="' + escapeAttr(opts.max) + '"' : '') +
      (opts.step != null ? ' step="' + escapeAttr(opts.step) + '"' : '') +
      '>');
    parts.push('</div>');
    return parts.join('');
  }

  function buildDateInput(opts) {
    opts = opts || {};
    var isFilter = opts.type === 'filter';
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, isFilter));
    parts.push('<input type="date"' +
      ' data-param="' + escapeAttr(opts.param || opts.field) + '"' +
      ' style="' + (isFilter ? FILTER_INPUT_STYLE : INPUT_STYLE) + '"' +
      ' value="' + escapeAttr(opts.default) + '"' +
      (opts.min != null ? ' min="' + escapeAttr(opts.min) + '"' : '') +
      (opts.max != null ? ' max="' + escapeAttr(opts.max) + '"' : '') +
      '>');
    parts.push('</div>');
    return parts.join('');
  }

  function buildTextInput(opts) {
    opts = opts || {};
    var isFilter = opts.type === 'filter';
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, isFilter));
    parts.push('<input type="text"' +
      ' data-param="' + escapeAttr(opts.param || opts.field) + '"' +
      ' style="' + (isFilter ? FILTER_INPUT_STYLE : INPUT_STYLE) + '"' +
      ' value="' + escapeAttr(opts.default) + '"' +
      '>');
    parts.push('</div>');
    return parts.join('');
  }

  function buildMultiSelect(opts) {
    opts = opts || {};
    var options = _parseOptions(opts.options);
    var defaults = opts.default;
    if (defaults != null && typeof defaults === 'string') {
      try { defaults = JSON.parse(defaults); } catch (e) { defaults = []; }
    }
    var defaultArr = Array.isArray(defaults) ? defaults.map(String) : null;
    var allChecked = defaultArr === null;

    var parts = [];
    parts.push('<div class="shelves-control" style="' + LIST_WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, true));
    parts.push('<div class="shelves-multi-select" style="' + LIST_BOX_STYLE + '">');
    // All toggle
    parts.push('<label style="' + LIST_ITEM_ALL_STYLE + '">' +
      '<input type="checkbox" value="__all__"' + (allChecked ? ' checked' : '') + '> All</label>');
    for (var i = 0; i < options.length; i++) {
      var o = options[i];
      var checked = allChecked || (defaultArr && defaultArr.indexOf(String(o.value)) >= 0);
      parts.push('<label style="' + LIST_ITEM_STYLE + '">' +
        '<input type="checkbox" value="' + escapeAttr(o.value) + '"' + (checked ? ' checked' : '') + '> ' +
        escapeAttr(o.label) + '</label>');
    }
    parts.push('</div>');
    parts.push('</div>');
    return parts.join('');
  }

  // multi mode, dropdown:true — a compact native <select multiple> listbox.
  // No "All" option: an empty selection means unfiltered (null).
  function buildNativeMultiSelect(opts) {
    opts = opts || {};
    var options = _parseOptions(opts.options);
    var defaults = opts.default;
    if (defaults != null && typeof defaults === 'string') {
      try { defaults = JSON.parse(defaults); } catch (e) { defaults = []; }
    }
    var defaultArr = Array.isArray(defaults) ? defaults.map(String) : null;

    // Show a few rows so the listbox reads as a multi-select, not a clipped
    // one-liner; scroll for the rest. Clamp to [2, 6].
    var size = Math.min(Math.max(options.length, 2), 6);
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, true));
    parts.push('<select multiple size="' + size + '" data-param="' + escapeAttr(opts.param || opts.field) +
      '" style="' + NATIVE_MULTI_STYLE + '">');
    for (var i = 0; i < options.length; i++) {
      var o = options[i];
      var sel = (defaultArr && defaultArr.indexOf(String(o.value)) >= 0) ? ' selected' : '';
      parts.push('<option value="' + escapeAttr(o.value) + '"' + sel + '>' +
        escapeAttr(o.label) + '</option>');
    }
    parts.push('</select>');
    parts.push('</div>');
    return parts.join('');
  }

  // single mode, dropdown:false — a top-aligned, scrollable radio list with an
  // "All" (unfiltered) option.
  function buildSingleList(opts) {
    opts = opts || {};
    var options = _parseOptions(opts.options);
    var current = opts.default;
    var name = 'sl-' + escapeAttr((opts.model || '') + '-' + (opts.field || opts.param || ''));

    var parts = [];
    parts.push('<div class="shelves-control" style="' + LIST_WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, true));
    parts.push('<div class="shelves-single-list" style="' + LIST_BOX_STYLE + '">');
    var allChecked = (current == null) ? ' checked' : '';
    parts.push('<label style="' + LIST_ITEM_ALL_STYLE + '">' +
      '<input type="radio" name="' + name + '" value=""' + allChecked + '> All</label>');
    for (var i = 0; i < options.length; i++) {
      var o = options[i];
      var checked = (current != null && String(o.value) === String(current)) ? ' checked' : '';
      parts.push('<label style="' + LIST_ITEM_STYLE + '">' +
        '<input type="radio" name="' + name + '" value="' + escapeAttr(o.value) + '"' + checked + '> ' +
        escapeAttr(o.label) + '</label>');
    }
    parts.push('</div>');
    parts.push('</div>');
    return parts.join('');
  }

  // ─── range / date_range (SHE-84) ───────────────────────────
  // Both render a library skeleton when their CDN lib is present, else a native
  // fallback — chosen here in the pure builder so the choice is unit-testable
  // and export/Studio behave identically when a load fails. Bounds and default
  // ride on the wrapper's data-* so the wiring can read them without re-parsing.

  function _hasLib(name) {
    try {
      return typeof global[name] !== 'undefined' && !!global[name];
    } catch (e) {
      return false;
    }
  }

  function _parsePair(raw) {
    var v = raw;
    if (typeof v === 'string') {
      try { v = JSON.parse(v); } catch (e) { return null; }
    }
    return Array.isArray(v) && v.length === 2 ? v : null;
  }

  function serializeRange(lo, hi) {
    return [Number(lo), Number(hi)];
  }

  function serializeDateRange(a, b) {
    return a && b ? [a, b] : null;
  }

  var RANGE_VALUE_STYLE = 'font-size:var(--shelves-filter-font-size,13px);' +
    'color:var(--shelves-filter-text,#1a1a1a);margin-top:6px';

  function buildRange(opts) {
    opts = opts || {};
    var bounds = _parseOptions(opts.options);
    var min = bounds.length ? bounds[0] : 0;
    var max = bounds.length > 1 ? bounds[1] : 100;
    var def = _parsePair(opts.default) || [min, max];
    var lo = def[0];
    var hi = def[1];
    var step = opts.step != null ? opts.step : '';

    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, true));
    parts.push('<div class="shelves-range" data-min="' + escapeAttr(min) +
      '" data-max="' + escapeAttr(max) + '"' +
      (step !== '' ? ' data-step="' + escapeAttr(step) + '"' : '') +
      ' data-default="' + escapeAttr(JSON.stringify([lo, hi])) + '">');

    if (_hasLib('noUiSlider')) {
      parts.push('<div class="shelves-range-slider" style="margin:16px 6px 4px"></div>');
    } else {
      var stepAttr = step !== '' ? ' step="' + escapeAttr(step) + '"' : '';
      parts.push('<input type="range" class="shelves-range-lo" min="' + escapeAttr(min) +
        '" max="' + escapeAttr(max) + '"' + stepAttr + ' value="' + escapeAttr(lo) +
        '" style="width:100%">');
      parts.push('<input type="range" class="shelves-range-hi" min="' + escapeAttr(min) +
        '" max="' + escapeAttr(max) + '"' + stepAttr + ' value="' + escapeAttr(hi) +
        '" style="width:100%">');
    }
    parts.push('<div class="shelves-range-value" style="' + RANGE_VALUE_STYLE + '">' +
      escapeAttr(lo) + ' – ' + escapeAttr(hi) + '</div>');
    parts.push('</div>');
    parts.push('</div>');
    return parts.join('');
  }

  function buildDateRange(opts) {
    opts = opts || {};
    var bounds = _parseOptions(opts.options);
    var min = bounds.length ? bounds[0] : '';
    var max = bounds.length > 1 ? bounds[1] : '';
    var def = _parsePair(opts.default) || [];
    var start = def[0] != null ? def[0] : '';
    var end = def[1] != null ? def[1] : '';
    var inputType = _hasLib('flatpickr') ? 'text' : 'date';
    var minAttr = min !== '' ? ' min="' + escapeAttr(min) + '"' : '';
    var maxAttr = max !== '' ? ' max="' + escapeAttr(max) + '"' : '';
    var ro = inputType === 'text' ? ' readonly' : '';
    var half = FILTER_INPUT_STYLE + ';width:50%';

    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, true));
    parts.push('<div class="shelves-daterange" data-min="' + escapeAttr(min) +
      '" data-max="' + escapeAttr(max) + '" style="display:flex;gap:6px">');
    parts.push('<input type="' + inputType + '" class="shelves-daterange-start"' +
      minAttr + maxAttr + ro + ' value="' + escapeAttr(start) +
      '" placeholder="Start" style="' + half + '">');
    parts.push('<input type="' + inputType + '" class="shelves-daterange-end"' +
      minAttr + maxAttr + ro + ' value="' + escapeAttr(end) +
      '" placeholder="End" style="' + half + '">');
    parts.push('</div>');
    parts.push('</div>');
    return parts.join('');
  }

  function _formatStaticValue(opts) {
    var mode = opts.mode;
    var val = opts.default;
    var options = _parseOptions(opts.options);
    var control = opts.control;

    // Mode-specific formatting for filters
    if (mode === 'multi') {
      if (val == null) return 'All';
      var arr = Array.isArray(val) ? val : [val];
      var labels = arr.map(function (v) {
        for (var i = 0; i < options.length; i++) {
          if (String(options[i].value) === String(v)) return options[i].label;
        }
        return String(v);
      });
      return escapeAttr(labels.join(', '));
    }
    if (mode === 'wildcard') {
      if (val == null || val === '') return 'All';
      return 'contains &quot;' + escapeAttr(val) + '&quot;';
    }
    if (mode === 'range') {
      if (val == null) return 'All';
      if (Array.isArray(val)) return escapeAttr(String(val[0])) + ' – ' + escapeAttr(String(val[1]));
      return escapeAttr(String(val));
    }
    if (mode === 'at_least') {
      if (val == null) return 'All';
      return '≥ ' + escapeAttr(String(val));
    }
    if (mode === 'at_most') {
      if (val == null) return 'All';
      return '≤ ' + escapeAttr(String(val));
    }
    if (mode === 'after') {
      if (val == null) return 'All';
      return 'on or after ' + escapeAttr(String(val));
    }
    if (mode === 'before') {
      if (val == null) return 'All';
      return 'on or before ' + escapeAttr(String(val));
    }
    if (mode === 'single') {
      if (val == null) return 'All';
      for (var s = 0; s < options.length; s++) {
        if (String(options[s].value) === String(val)) return escapeAttr(options[s].label);
      }
      return escapeAttr(String(val));
    }

    // Default: parameter-style formatting
    if (val == null) return 'All';

    if (control === 'dropdown') {
      for (var i = 0; i < options.length; i++) {
        if (String(options[i].value) === String(val)) return escapeAttr(options[i].label);
      }
      return escapeAttr(String(val));
    }
    if (control === 'text') {
      if (val === '') return '—';
      return escapeAttr(String(val));
    }
    return escapeAttr(String(val));
  }

  function buildStaticValue(opts) {
    opts = opts || {};
    var isFilter = opts.type === 'filter';
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, isFilter));
    parts.push('<span style="' + (isFilter ? FILTER_STATIC_VALUE_STYLE : STATIC_VALUE_STYLE) + '">' +
      _formatStaticValue(opts) + '</span>');
    parts.push('</div>');
    return parts.join('');
  }

  function buildControl(attrs) {
    attrs = attrs || {};
    var widget = attrs.control;
    if (widget === 'dropdown') return buildDropdown(attrs);
    if (widget === 'stepper') return buildStepper(attrs);
    if (widget === 'date') return buildDateInput(attrs);
    if (widget === 'text') return buildTextInput(attrs);
    if (widget === 'multi_select') return buildMultiSelect(attrs);
    if (widget === 'multi_dropdown') return buildNativeMultiSelect(attrs);
    if (widget === 'single_list') return buildSingleList(attrs);
    if (widget === 'range') return buildRange(attrs);
    if (widget === 'date_range') return buildDateRange(attrs);
    return '';
  }

  function _parseAttr(raw) {
    if (raw == null) return raw;
    try { return JSON.parse(raw); } catch (e) { return raw; }
  }

  function render(doc) {
    doc = doc || (typeof document !== 'undefined' ? document : null);
    if (!doc) return;
    var divs = doc.querySelectorAll('div[data-control]');
    var inStudio = typeof window !== 'undefined' && !!window.__SHELVES_INTERACTIVE__;

    Array.prototype.forEach.call(divs, function (div) {
      var dataType = div.getAttribute('data-type');
      var isFilter = dataType === 'filter';

      var attrs = {
        control: div.getAttribute('data-control'),
        title: div.getAttribute('data-title') || '',
        default: _parseAttr(div.getAttribute('data-default')),
        options: div.getAttribute('data-options'),
        min: div.getAttribute('data-min'),
        max: div.getAttribute('data-max'),
        step: div.getAttribute('data-step'),
        type: dataType,
      };

      if (isFilter) {
        attrs.field = div.getAttribute('data-field');
        attrs.model = div.getAttribute('data-model');
        attrs.mode = div.getAttribute('data-mode');
        attrs.operator = div.getAttribute('data-operator');
        attrs.targets = div.getAttribute('data-targets');
      } else {
        attrs.param = div.getAttribute('data-param');
      }

      if (!inStudio) {
        div.innerHTML = buildStaticValue(attrs);
        return;
      }

      // Isolate each control: a library init that throws (bad CDN payload,
      // unexpected DOM) must not abort the loop and leave later controls unbuilt.
      try {
        var markup = buildControl(attrs);
        if (!markup) return;
        div.innerHTML = markup;

        if (isFilter) {
          _wireFilterEvents(div, attrs);
        } else {
          _wireParamEvents(div, attrs);
        }
      } catch (e) {
        if (typeof console !== 'undefined' && console.error) {
          console.error('shelves: control render failed', e);
        }
      }
    });
  }

  function _wireParamEvents(div, attrs) {
    var input = div.querySelector('select, input');
    if (!input) return;
    input.addEventListener('change', function () {
      window.parent.postMessage({
        type: 'shelves:param-change',
        param: attrs.param,
        value: input.value,
      }, '*');
    });
  }

  var _filterDebounceTimers = {};

  function _wireFilterEvents(div, attrs) {
    var widget = attrs.control;

    if (widget === 'multi_select') {
      var container = div.querySelector('.shelves-multi-select');
      if (!container) return;
      container.addEventListener('change', function (e) {
        var allToggle = container.querySelector('input[value="__all__"]');
        var checkboxes = container.querySelectorAll('input[type="checkbox"]:not([value="__all__"])');
        // Toggling "All" itself drives every box to match and means unfiltered.
        // Toggling an individual box must NOT be overridden by "All" still being
        // checked — otherwise the first narrowing click snaps straight back.
        if (allToggle && e.target === allToggle) {
          Array.prototype.forEach.call(checkboxes, function (cb) { cb.checked = allToggle.checked; });
          _postFilterChange(attrs, null);
          return;
        }
        var selected = [];
        Array.prototype.forEach.call(checkboxes, function (cb) {
          if (cb.checked) selected.push(cb.value);
        });
        // Everything checked (or nothing) is equivalent to "All" → unfiltered.
        var everyChecked = checkboxes.length > 0 && selected.length === checkboxes.length;
        if (allToggle) allToggle.checked = everyChecked;
        _postFilterChange(attrs, (everyChecked || selected.length === 0) ? null : selected);
      });
      return;
    }

    if (widget === 'dropdown') {
      var select = div.querySelector('select');
      if (!select) return;
      select.addEventListener('change', function () {
        var val = select.value === '' ? null : select.value;
        _postFilterChange(attrs, val);
      });
      return;
    }

    if (widget === 'multi_dropdown') {
      var multi = div.querySelector('select[multiple]');
      if (!multi) return;
      multi.addEventListener('change', function () {
        var selected = [];
        Array.prototype.forEach.call(multi.options, function (o) {
          if (o.selected) selected.push(o.value);
        });
        _postFilterChange(attrs, selected.length > 0 ? selected : null);
      });
      // Upgrade the native <select multiple> to a collapsing, tokenized Tom
      // Select when the lib loaded. It keeps the underlying <select> in sync and
      // fires native `change`, so the listener above still drives the commit.
      // The native listbox is the degrade-gracefully fallback when it didn't.
      if (_hasLib('TomSelect')) {
        try {
          // dropdownParent:'body' lifts the open list out of the filter node's
          // overflow:hidden box (the SHE-82 fit clip) so it can overflow the
          // widget and scroll internally instead of being cut off.
          new global.TomSelect(multi, {
            plugins: ['remove_button'],
            maxOptions: null,
            dropdownParent: 'body',
          });
        } catch (e) { /* keep the native listbox */ }
      }
      return;
    }

    if (widget === 'range') {
      _wireRange(div, attrs);
      return;
    }

    if (widget === 'date_range') {
      _wireDateRange(div, attrs);
      return;
    }

    if (widget === 'single_list') {
      var list = div.querySelector('.shelves-single-list');
      if (!list) return;
      list.addEventListener('change', function () {
        var checked = list.querySelector('input[type="radio"]:checked');
        var val = (checked && checked.value !== '') ? checked.value : null;
        _postFilterChange(attrs, val);
      });
      return;
    }

    if (widget === 'text') {
      var textInput = div.querySelector('input[type="text"]');
      if (!textInput) return;
      textInput.addEventListener('input', function () {
        var key = (attrs.model || '') + '.' + (attrs.field || '');
        clearTimeout(_filterDebounceTimers[key]);
        var currentVal = textInput.value;
        _filterDebounceTimers[key] = setTimeout(function () {
          _postFilterChange(attrs, currentVal || null);
        }, 300);
      });
      return;
    }

    // Stepper, date — same as param but with filter event
    var input = div.querySelector('input');
    if (!input) return;
    input.addEventListener('change', function () {
      var val = input.value === '' ? null : input.value;
      _postFilterChange(attrs, val);
    });
  }

  function _isoDate(d) {
    if (typeof d === 'string') return d;
    if (d && typeof d.toISOString === 'function') return d.toISOString().slice(0, 10);
    return '';
  }

  // range: label tracks the drag live; the filter commits only on drag-end
  // (noUiSlider `change`, native `change`) — a per-move commit floods the
  // recompile loop. A selection spanning the full bounds means unfiltered.
  function _wireRange(div, attrs) {
    var box = div.querySelector('.shelves-range');
    if (!box) return;
    var min = Number(box.getAttribute('data-min'));
    var max = Number(box.getAttribute('data-max'));
    var stepAttr = box.getAttribute('data-step');
    var def = _parsePair(box.getAttribute('data-default')) || [min, max];
    var valueEl = box.querySelector('.shelves-range-value');

    function setLabel(lo, hi) {
      if (valueEl) valueEl.textContent = lo + ' – ' + hi;
    }
    function commit(lo, hi) {
      var full = Number(lo) <= min && Number(hi) >= max;
      _postFilterChange(attrs, full ? null : serializeRange(lo, hi));
    }

    if (_hasLib('noUiSlider')) {
      var mount = box.querySelector('.shelves-range-slider');
      if (!mount) return;
      var cfg = { start: def, connect: true, range: { min: min, max: max } };
      if (stepAttr) cfg.step = Number(stepAttr);
      global.noUiSlider.create(mount, cfg);
      mount.noUiSlider.on('update', function (v) { setLabel(Number(v[0]), Number(v[1])); });
      mount.noUiSlider.on('change', function (v) { commit(Number(v[0]), Number(v[1])); });
      return;
    }

    var loEl = box.querySelector('.shelves-range-lo');
    var hiEl = box.querySelector('.shelves-range-hi');
    if (!loEl || !hiEl) return;
    function read() {
      var lo = Number(loEl.value);
      var hi = Number(hiEl.value);
      return lo > hi ? [hi, lo] : [lo, hi]; // guard handle crossing
    }
    function live() { var r = read(); setLabel(r[0], r[1]); }
    function done() { var r = read(); commit(r[0], r[1]); }
    loEl.addEventListener('input', live);
    hiEl.addEventListener('input', live);
    loEl.addEventListener('change', done);
    hiEl.addEventListener('change', done);
  }

  function _wireDateRange(div, attrs) {
    var box = div.querySelector('.shelves-daterange');
    if (!box) return;
    var startEl = box.querySelector('.shelves-daterange-start');
    var endEl = box.querySelector('.shelves-daterange-end');
    if (!startEl || !endEl) return;
    var dmin = box.getAttribute('data-min') || undefined;
    var dmax = box.getAttribute('data-max') || undefined;

    if (_hasLib('flatpickr')) {
      var opts = {
        dateFormat: 'Y-m-d',
        minDate: dmin,
        maxDate: dmax,
        onClose: function (sel) {
          if (sel && sel.length === 2) {
            _postFilterChange(attrs, serializeDateRange(_isoDate(sel[0]), _isoDate(sel[1])));
          } else if (!sel || sel.length === 0) {
            _postFilterChange(attrs, null);
          }
        },
      };
      if (global.rangePlugin) opts.plugins = [global.rangePlugin({ input: endEl })];
      if (startEl.value && endEl.value) opts.defaultDate = [startEl.value, endEl.value];
      global.flatpickr(startEl, opts);
      return;
    }

    function commit() {
      _postFilterChange(attrs, serializeDateRange(startEl.value, endEl.value));
    }
    startEl.addEventListener('change', commit);
    endEl.addEventListener('change', commit);
  }

  function _postFilterChange(attrs, value) {
    window.parent.postMessage({
      type: 'shelves:filter-change',
      field: attrs.field,
      model: attrs.model,
      value: value,
      mode: attrs.mode,
      operator: attrs.operator,
    }, '*');
  }

  var api = {
    escapeAttr: escapeAttr,
    buildDropdown: buildDropdown,
    buildStepper: buildStepper,
    buildDateInput: buildDateInput,
    buildTextInput: buildTextInput,
    buildMultiSelect: buildMultiSelect,
    buildNativeMultiSelect: buildNativeMultiSelect,
    buildSingleList: buildSingleList,
    buildRange: buildRange,
    buildDateRange: buildDateRange,
    serializeRange: serializeRange,
    serializeDateRange: serializeDateRange,
    buildStaticValue: buildStaticValue,
    buildControl: buildControl,
    render: render,
  };

  global.controlRender = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
