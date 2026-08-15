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
      'font-weight:500;margin-bottom:4px;white-space:nowrap';
  }
  function _inputStyle(p) {
    return 'font-size:var(--shelves-' + p + '-font-size,13px);' +
      'height:var(--shelves-' + p + '-height,32px);' +
      'border:1px solid var(--shelves-' + p + '-border,#e5e7eb);' +
      'border-radius:var(--shelves-' + p + '-radius,4px);' +
      'background:var(--shelves-' + p + '-surface,#ffffff);' +
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

  function buildRangeStub(opts) {
    opts = opts || {};
    var widget = opts.control || 'range';
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title, true));
    parts.push('<div style="' +
      'font-size:var(--shelves-filter-font-size,13px);' +
      'color:var(--shelves-filter-border,#9ca3af);' +
      'padding:6px 0">' + escapeAttr(widget) + ' widget — requires SHE-84</div>');
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
    if (widget === 'range' || widget === 'date_range') return buildRangeStub(attrs);
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

      var markup = buildControl(attrs);
      if (!markup) return;
      div.innerHTML = markup;

      if (isFilter) {
        _wireFilterEvents(div, attrs);
      } else {
        _wireParamEvents(div, attrs);
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
    buildRangeStub: buildRangeStub,
    buildStaticValue: buildStaticValue,
    buildControl: buildControl,
    render: render,
  };

  global.controlRender = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
