// control_render.js — browser-side rendering for dashboard parameter controls.
//
// SHE-92 bakes data-param/data-control/data-options/data-default/data-title
// onto each control placeholder div. This script reads those attributes and
// builds native HTML form elements (select, input[number], input[date],
// input[text]). In Studio, changing a control posts a message to the parent
// frame; in exported HTML, controls render as disabled (no server to recompile).
//
// Follows the legend_render.js pattern exactly: IIFE, plain global
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

  var LABEL_STYLE = 'font-size:var(--shelves-control-font-size,13px);' +
    'font-weight:500;margin-bottom:4px;white-space:nowrap';
  var INPUT_STYLE = 'font-size:var(--shelves-control-font-size,13px);' +
    'height:var(--shelves-control-height,32px);' +
    'border:1px solid var(--shelves-control-border,#e5e7eb);' +
    'border-radius:var(--shelves-control-radius,4px);' +
    'background:var(--shelves-control-surface,#ffffff);' +
    'padding:0 8px;box-sizing:border-box;width:100%';
  var WRAP_STYLE = 'display:flex;flex-direction:column';

  function titleMarkup(title) {
    if (!title) return '';
    return '<label style="' + LABEL_STYLE + '">' + escapeAttr(title) + '</label>';
  }

  function buildDropdown(opts) {
    opts = opts || {};
    var options = opts.options;
    if (typeof options === 'string') {
      try { options = JSON.parse(options); } catch (e) { options = []; }
    }
    options = options || [];
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title));
    parts.push('<select data-param="' + escapeAttr(opts.param) + '" style="' + INPUT_STYLE + '">');
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
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title));
    parts.push('<input type="number"' +
      ' data-param="' + escapeAttr(opts.param) + '"' +
      ' style="' + INPUT_STYLE + '"' +
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
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title));
    parts.push('<input type="date"' +
      ' data-param="' + escapeAttr(opts.param) + '"' +
      ' style="' + INPUT_STYLE + '"' +
      ' value="' + escapeAttr(opts.default) + '"' +
      (opts.min != null ? ' min="' + escapeAttr(opts.min) + '"' : '') +
      (opts.max != null ? ' max="' + escapeAttr(opts.max) + '"' : '') +
      '>');
    parts.push('</div>');
    return parts.join('');
  }

  function buildTextInput(opts) {
    opts = opts || {};
    var parts = [];
    parts.push('<div class="shelves-control" style="' + WRAP_STYLE + '">');
    parts.push(titleMarkup(opts.title));
    parts.push('<input type="text"' +
      ' data-param="' + escapeAttr(opts.param) + '"' +
      ' style="' + INPUT_STYLE + '"' +
      ' value="' + escapeAttr(opts.default) + '"' +
      '>');
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
    return '';
  }

  function _parseAttr(raw) {
    if (raw == null) return raw;
    try { return JSON.parse(raw); } catch (e) { return raw; }
  }

  // Browser-only: fill every control div, wire change listeners.
  function render(doc) {
    doc = doc || (typeof document !== 'undefined' ? document : null);
    if (!doc) return;
    var divs = doc.querySelectorAll('div[data-param][data-control]');
    var inStudio = !!window.__SHELVES_INTERACTIVE__;

    Array.prototype.forEach.call(divs, function (div) {
      var attrs = {
        param: div.getAttribute('data-param'),
        control: div.getAttribute('data-control'),
        title: div.getAttribute('data-title') || '',
        default: _parseAttr(div.getAttribute('data-default')),
        options: div.getAttribute('data-options'),
        min: div.getAttribute('data-min'),
        max: div.getAttribute('data-max'),
        step: div.getAttribute('data-step'),
      };
      var markup = buildControl(attrs);
      if (!markup) return;
      div.innerHTML = markup;

      var input = div.querySelector('select, input');
      if (!input) return;

      if (!inStudio) {
        input.disabled = true;
        return;
      }

      input.addEventListener('change', function () {
        window.parent.postMessage({
          type: 'shelves:param-change',
          param: attrs.param,
          value: input.value,
        }, '*');
      });
    });
  }

  var api = {
    escapeAttr: escapeAttr,
    buildDropdown: buildDropdown,
    buildStepper: buildStepper,
    buildDateInput: buildDateInput,
    buildTextInput: buildTextInput,
    buildControl: buildControl,
    render: render,
  };

  global.controlRender = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
