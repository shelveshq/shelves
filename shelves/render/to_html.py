"""
HTML Renderer

Produces a standalone HTML page that renders a Vega-Lite spec
using vegaEmbed from CDN.

Phase 1 rendering approach -- open in browser for visual verification.
Phase 6 replaces this with a web app component.
"""

from __future__ import annotations

import html
import json


def render_html(spec: dict, title: str | None = None) -> str:
    """Generate a standalone HTML page embedding a Vega-Lite spec."""
    spec_json = json.dumps(spec, indent=2).replace("</", r"<\/")
    page_title = title or spec.get("title", "Charter -- Chart Preview")
    page_title = html.escape(str(page_title), quote=True)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{page_title}</title>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@6"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
  <style>
    body {{
      margin: 0; padding: 24px;
      font-family: Inter, system-ui, sans-serif;
      background: #f5f5f5;
    }}
    #chart {{
      background: #ffffff; border-radius: 8px;
      padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
  </style>
</head>
<body>
  <div id="chart"></div>
  <script>
    function findNamedMark(marks, name) {{
      if (!marks) return null;
      for (const m of marks) {{
        if (m.name === name || m.name === name + '_marks') return m;
        if (m.marks) {{
          const found = findNamedMark(m.marks, name);
          if (found) return found;
        }}
      }}
      return null;
    }}

    function insertAfterMark(marks, target, newMark) {{
      if (!marks) return false;
      for (let i = 0; i < marks.length; i++) {{
        if (marks[i] === target) {{
          marks.splice(i + 1, 0, newMark);
          return true;
        }}
        if (marks[i].marks && insertAfterMark(marks[i].marks, target, newMark)) {{
          return true;
        }}
      }}
      return false;
    }}

    function charterPatch(vgSpec) {{
      const labels = vgSpec.usermeta?.charter?.labels;
      if (!labels || labels.length === 0) return vgSpec;

      for (const intent of labels) {{
        const mark = findNamedMark(vgSpec.marks, intent.markName);
        if (!mark || mark.type !== 'rect') continue;

        const enc = mark.encode?.update;
        if (!enc) continue;

        const isHBar = !!enc.height;
        const textEnc = {{}};

        if (isHBar) {{
          if (enc.y) {{
            textEnc.y = JSON.parse(JSON.stringify(enc.y));
            // Compiled Vega puts the band width on a separate height signal;
            // the y ref is {{scale, field}} with no band key. Always center on
            // the band so the label sits over the bar, not its leading edge.
            textEnc.y.band = 0.5;
          }}
          const hPos = intent.horizontal || 'center';
          if (hPos === 'left') {{
            if (enc.x2) textEnc.x = JSON.parse(JSON.stringify(enc.x2));
            textEnc.align = {{ value: 'right' }};
            textEnc.dx = {{ value: -4 }};
          }} else {{
            if (enc.x) textEnc.x = JSON.parse(JSON.stringify(enc.x));
            textEnc.align = {{ value: 'left' }};
            textEnc.dx = {{ value: 4 }};
          }}
          textEnc.baseline = {{ value: 'middle' }};
        }} else {{
          if (enc.x) {{
            textEnc.x = JSON.parse(JSON.stringify(enc.x));
            // Compiled Vega puts the band width on a separate width signal;
            // the x ref is {{scale, field}} with no band key. Always center on
            // the band so the label sits over the bar, not its leading edge.
            textEnc.x.band = 0.5;
          }}
          const vPos = intent.vertical || 'center';
          if (vPos === 'bottom') {{
            if (enc.y2) textEnc.y = JSON.parse(JSON.stringify(enc.y2));
            textEnc.baseline = {{ value: 'top' }};
            textEnc.dy = {{ value: 4 }};
          }} else {{
            if (enc.y) textEnc.y = JSON.parse(JSON.stringify(enc.y));
            textEnc.baseline = {{ value: 'bottom' }};
            textEnc.dy = {{ value: -4 }};
          }}
          textEnc.align = {{ value: 'center' }};
        }}

        const mField = isHBar ? enc.x?.field : enc.y?.field;
        const bField = isHBar ? enc.x2?.field : enc.y2?.field;
        const isStacked = !!(bField && mField && bField !== mField);

        if (intent.format) {{
          const expr = isStacked
            ? "format(datum['" + mField + "'] - datum['" + bField + "'], '" + intent.format + "')"
            : "format(datum['" + (mField || intent.field) + "'], '" + intent.format + "')";
          textEnc.text = {{ signal: expr }};
        }} else if (isStacked) {{
          textEnc.text = {{ signal: "datum['" + mField + "'] - datum['" + bField + "']" }};
        }} else {{
          textEnc.text = {{ field: mField || intent.field }};
        }}

        textEnc.fontSize = {{ value: intent.size || 11 }};
        if (intent.color === 'match' && enc.fill) {{
          textEnc.fill = JSON.parse(JSON.stringify(enc.fill));
        }} else {{
          textEnc.fill = {{ value: intent.color || '#333333' }};
        }}

        const textMark = {{
          type: 'text',
          from: JSON.parse(JSON.stringify(mark.from)),
          encode: {{ update: textEnc }}
        }};
        insertAfterMark(vgSpec.marks, mark, textMark);
      }}
      return vgSpec;
    }}

    const spec = {spec_json};
    vegaEmbed('#chart', spec, {{
      renderer: 'canvas',
      patch: charterPatch,
      actions: {{ export: true, source: true, compiled: false, editor: true }}
    }}).catch(console.error);
  </script>
</body>
</html>"""
