# Design: Compile-then-Patch Labels

> **Status:** Exploration (branch off main, merge if successful)
> **Epic:** [KAN-279](https://vj-and-team.atlassian.net/browse/KAN-279)
> **Base commit:** `0d8b39a` (pre-labels — revert all current label work)
> **Driver:** Vega-Lite cannot do collision-aware label placement or dynamic
> contrast coloring. The current pure-VL label system is increasingly brittle
> and will never support "just works" labels.
>
> **Stories:**
> | Stage | Ticket | Summary |
> |---|---|---|
> | 1 | [KAN-280](https://vj-and-team.atlassian.net/browse/KAN-280) | Patch seam scaffold |
> | 2 | [KAN-281](https://vj-and-team.atlassian.net/browse/KAN-281) | Emit usermeta label intent |
> | 3 | [KAN-282](https://vj-and-team.atlassian.net/browse/KAN-282) | Basic label rendering via JS patch |
> | 4 | [KAN-283](https://vj-and-team.atlassian.net/browse/KAN-283) | Collision-aware placement (label transform) |
> | 5 | [KAN-284](https://vj-and-team.atlassian.net/browse/KAN-284) | Dynamic contrast coloring |
> | 6 | [KAN-285](https://vj-and-team.atlassian.net/browse/KAN-285) | Point/circle mark labels |
> | 7 | [KAN-286](https://vj-and-team.atlassian.net/browse/KAN-286) | Cleanup and migration |
> | 8 | [KAN-287](https://vj-and-team.atlassian.net/browse/KAN-287) | Line/area mark labels (deferred) |

---

## Architecture

```
┌─────────────────────────────────┐
│  Python Pipeline (unchanged)    │
│                                 │
│  YAML → ChartSpec → Vega-Lite   │
│  + usermeta.charter.labels      │
│    (label intent per mark)      │
└──────────────┬──────────────────┘
               │  VL spec with usermeta
               ▼
┌─────────────────────────────────┐
│  Browser (vegaEmbed)            │
│                                 │
│  1. VL compiles → Vega          │
│  2. patch(vgSpec) runs:         │
│     a. reads usermeta           │
│     b. finds bar/line/… marks   │
│     c. adds label dataset       │
│        (sourced from mark)      │
│     d. adds label transform     │
│        (anchor candidates,      │
│         occupancy bitmap)       │
│     e. adds text mark with      │
│        overlap-based contrast   │
│  3. Vega renders final chart    │
└─────────────────────────────────┘
```

**Key principle:** Python owns label *intent* (what to label, preferred side,
format). JavaScript owns label *mechanics* (placement, collision, contrast).
The boundary is `usermeta`.

---

## `usermeta` Contract

The Python translator emits label intent in `usermeta.charter.labels` — an
array of label descriptors, one per labelable mark in the spec. Vega-Lite
copies `usermeta` verbatim into compiled Vega output.

```json
{
  "usermeta": {
    "charter": {
      "labels": [
        {
          "markName": "bars_0",
          "field": "revenue",
          "type": "quantitative",
          "format": "$,.0f",
          "side": "top",
          "size": 11,
          "color": null
        }
      ]
    }
  }
}
```

| Field | Type | Description |
|---|---|---|
| `markName` | string | Name of the mark in the compiled Vega spec to source labels from. Derived from the mark's position in the layer/concat tree. |
| `field` | string | The data field whose value to display. |
| `type` | string | Vega-Lite type (`"quantitative"`, `"nominal"`, etc.). |
| `format` | string \| null | d3-format string (e.g. `"$,.0f"`). |
| `side` | string | User's preferred side: `"top"`, `"bottom"`, `"left"`, `"right"`. Mapped to `anchor`/`offset` candidates in JS. |
| `size` | number | Font size in pixels. |
| `color` | string \| null | Explicit hex color override. When `null`, dynamic contrast is used. |

### Side → Anchor mapping

The user's `side` preference maps to a prioritized candidate list for the
Vega `label` transform:

| User side | Orientation | Primary anchor | Fallback anchor |
|---|---|---|---|
| `top` | vertical | `top-center` | `bottom-center` |
| `bottom` | vertical | `bottom-center` | `top-center` |
| `right` | horizontal | `right-center` | `left-center` |
| `left` | horizontal | `left-center` | `right-center` |

The `label` transform tries the primary anchor first; if it collides with the
occupancy bitmap, it tries the fallback; if both collide, the label is hidden
(`opacity: 0`).

For stacked bars, the side defaults to `"center"` — the label is anchored at
the geometric center of the segment with `avoidBaseMark: false`. If the
segment is too small, the label is hidden.

---

## Stages

Each stage is independently testable. A stage is **done** when its success
criteria pass visually in the dev server and programmatically in pytest.

---

### Stage 1: Patch seam scaffold

**Goal:** Prove the vegaEmbed `patch` callback works. No label logic yet.

**Files touched:**
- `shelves/render/to_html.py` — add `patch` function to vegaEmbed call

**Changes:**
1. Add a no-op `patch` callback to the vegaEmbed options:
   ```js
   vegaEmbed('#chart', spec, {
     renderer: 'canvas',
     patch: (vgSpec) => {
       console.log('[charter] patch seam active, marks:',
         vgSpec.marks?.length);
       return vgSpec;
     },
     actions: { ... }
   });
   ```
2. Open any fixture in the dev server and verify:
   - Chart renders identically to before
   - Console shows the patch log message with mark count

**Success criteria:**
- [ ] Dev server renders `simple_bar.yaml` unchanged
- [ ] Browser console shows `[charter] patch seam active, marks: N`
- [ ] No test regressions (`pytest` green)

---

### Stage 2: `usermeta` emission from Python

**Goal:** The translator emits label intent in `usermeta.charter.labels`
instead of building VL text layers. Labels disappear visually (expected —
the JS patch doesn't read them yet).

**Files touched:**
- `shelves/translator/labels.py` — rewrite to emit usermeta descriptors
- `shelves/translator/translate.py` — merge usermeta into top-level spec
- `shelves/translator/patterns/single.py` — call new label intent API
- `shelves/translator/patterns/stacked.py` — call new label intent API
- `shelves/translator/patterns/layers.py` — call new label intent API
- `shelves/schema/chart_schema.py` — simplify `LabelPosition` to 4 values
- `tests/test_labels.py` — rewrite to assert usermeta structure

**Design for `labels.py`:**

Replace the current 232-line module with a simpler API surface:

```python
def build_label_intent(
    mark_name: str,
    measure_field: str,
    label_config: LabelConfig,
    orientation: Literal["vertical", "horizontal"],
    resolver: FieldTypeResolver,
    is_stacked: bool = False,
) -> dict[str, Any]:
    """Build a usermeta label descriptor for a single mark."""
    side = _resolve_side(label_config.position, orientation, is_stacked)
    return {
        "markName": mark_name,
        "field": resolver.resolve_base_field(label_config.field or measure_field),
        "type": resolver.resolve(label_config.field or measure_field),
        "format": label_config.format or resolver.resolve_format(
            label_config.field or measure_field
        ),
        "side": side,
        "size": label_config.size or 11,
        "color": label_config.color,
    }
```

The functions `resolve_label_spec`, `resolve_label_cascade`, and
`detect_orientation` stay. Everything else (`build_label_layer`,
`wrap_spec_with_label`, `maybe_wrap_with_label`, `LABEL_POSITION_MAP`,
`_STACKED_CENTER_POSITION`, etc.) is removed.

**Schema change for `LabelPosition`:**

Simplify from 8 values to 4 cardinal directions. The inside/outside
distinction is now handled automatically by the placement algorithm.

```python
# Before:
LabelPosition = Literal[
    "top", "bottom", "left", "right",
    "inside-top", "inside-bottom", "inside-left", "inside-right",
]

# After:
LabelPosition = Literal["top", "bottom", "left", "right"]
```

DSL usage: `position: top` means "prefer the top side." The algorithm decides
whether that means inside-top or outside-top based on available space.

**Mark naming convention:**

Compiled Vega marks need stable names so the JS patch can find them. The
translator assigns names based on position in the spec tree:

- Single chart: `"mark_0"`
- Stacked `vconcat`/`hconcat`: `"mark_0"`, `"mark_1"`, ...
- Layer: `"layer_mark_0"`, `"layer_mark_1"`, ...

These are emitted as VL mark names (VL propagates `name` to compiled Vega):
```python
panel["mark"] = {"type": "bar", "name": "mark_0"}
```

**`translate.py` change:**

After the spec is built, collect all label intents and attach them:
```python
if label_intents:
    spec["usermeta"] = {"charter": {"labels": label_intents}}
```

**Success criteria:**
- [ ] `translate_chart(...)` on `label_bar_simple.yaml` produces a spec
      with `usermeta.charter.labels[0].side == "top"` (or default)
- [ ] No VL text layers in the output — label is intent-only
- [ ] Stacked fixtures produce `side: "center"` by default
- [ ] All label-related tests rewritten and passing
- [ ] Labels do NOT render visually yet (expected — JS patch is no-op)

---

### Stage 3: Basic label rendering via JS patch

**Goal:** The JS patch reads `usermeta.charter.labels`, finds the named
marks in the compiled Vega, and adds text marks with simple fixed
positioning (no collision avoidance yet). Visually equivalent to the old
pure-VL approach.

**Files touched:**
- `shelves/render/to_html.py` — implement the patch function

**Design for the patch function:**

```js
function charterPatch(vgSpec) {
  const labels = vgSpec.usermeta?.charter?.labels;
  if (!labels || labels.length === 0) return vgSpec;

  for (const intent of labels) {
    const mark = findMark(vgSpec.marks, intent.markName);
    if (!mark) continue;

    // Create a label dataset sourced from the mark's data
    const labelData = {
      name: intent.markName + '_labels',
      source: mark.from.data,
      transform: []  // Stage 4 adds the label transform here
    };

    // Create a text mark
    const textMark = {
      type: 'text',
      from: { data: labelData.name },
      encode: {
        enter: {
          text: { field: intent.field },
          fontSize: { value: intent.size },
          fill: { value: intent.color || '#333333' },
          // Position relative to the bar (simple version)
          ...simplePosition(intent.side, mark)
        }
      }
    };

    vgSpec.data.push(labelData);
    // Insert text mark after the source mark
    const markIdx = vgSpec.marks.indexOf(mark);
    vgSpec.marks.splice(markIdx + 1, 0, textMark);
  }
  return vgSpec;
}
```

**Testing approach:**

Since the patch runs in the browser, Python tests can't assert on the final
rendered output. Testing is split:

- **Python tests:** Assert `usermeta` structure is correct (Stage 2 tests)
- **Visual tests:** Dev server with label fixtures — verify labels appear
- **Snapshot tests (optional):** Capture vegaEmbed output specs for regression

**Success criteria:**
- [ ] `label_bar_simple.yaml` renders with labels in the dev server
- [ ] `label_grouped_bar.yaml` renders with per-segment labels
- [ ] `label_bar_horizontal.yaml` renders with horizontal labels
- [ ] Labels use fixed position matching old behavior (top/bottom/left/right)
- [ ] Non-bar marks still have no labels (not wired yet)

---

### Stage 4: Collision-aware placement via Vega `label` transform

**Goal:** Replace fixed positioning with the Vega `label` transform.
Labels auto-place based on the user's preferred side, fall back to the
opposite side on collision, and hide when nothing fits.

**Files touched:**
- `shelves/render/to_html.py` — update patch function to use `label` transform

**Design:**

Replace the simple text mark with a label-transform pipeline:

```js
// Label dataset: source from the mark, apply label transform
const labelData = {
  name: intent.markName + '_labels',
  source: intent.markName,  // source from the MARK, not the data
  transform: [{
    type: 'label',
    size: [{ signal: 'width' }, { signal: 'height' }],
    anchor: anchorCandidates(intent.side),
    offset: [1, -1],  // try outside first, then inside
    avoidBaseMark: intent.side !== 'center',
    sort: { field: 'datum.' + intent.field, order: 'descending' }
  }]
};

// Text mark reads placed positions from the transform
const textMark = {
  type: 'text',
  from: { data: labelData.name },
  encode: {
    update: {
      text: formatExpr(intent),
      fontSize: { value: intent.size },
      x: { field: 'x' },
      y: { field: 'y' },
      align: { field: 'align' },
      baseline: { field: 'baseline' },
      opacity: { field: 'opacity' },
      fill: { value: '#333333' }  // Stage 5 makes this dynamic
    }
  }
};
```

**`anchorCandidates` mapping:**

```js
function anchorCandidates(side) {
  switch (side) {
    case 'top':    return ['top', 'bottom'];
    case 'bottom': return ['bottom', 'top'];
    case 'left':   return ['left', 'right'];
    case 'right':  return ['right', 'left'];
    case 'center': return ['center'];
  }
}
```

**Stacked segment behavior:**

For stacked bars, each segment is a separate data point in the mark.
Setting `avoidBaseMark: false` anchors the label inside the segment. The
label transform uses the segment's pixel bounds — small segments get
hidden automatically. No `size/2` math, no sort-drift bug.

**Success criteria:**
- [ ] Simple bar: labels prefer user's side, fall back to opposite
- [ ] Dense bar chart: overlapping labels are hidden (opacity: 0)
- [ ] Stacked bar: each segment labeled at center, small segments hidden
- [ ] Horizontal bar: same behavior, rotated
- [ ] Changing `position: bottom` in YAML flips primary anchor
- [ ] No label-on-label overlap in any fixture

---

### Stage 5: Dynamic contrast coloring

**Goal:** Labels that land on top of a mark are white; labels off the mark
are dark. Determined per-label based on actual placed position, not static
config.

**Files touched:**
- `shelves/render/to_html.py` — add overlap detection + conditional fill

**Design:**

After the `label` transform places each label, we know:
- The label's final `x`, `y` position
- The source mark's bounding box (`bounds`)

Add a post-label-transform formula that checks containment:

```js
{
  type: 'formula',
  as: '__overlaps_mark',
  expr: `
    datum.datum.x != null &&
    datum.x >= datum.bounds.x1 &&
    datum.x <= datum.bounds.x2 &&
    datum.y >= datum.bounds.y1 &&
    datum.y <= datum.bounds.y2
  `
}
```

Then the text mark fill becomes conditional:

```js
fill: [
  // If user explicitly set a color, use it always
  intent.color
    ? { value: intent.color }
    : {
        test: 'datum.__overlaps_mark',
        value: '#ffffff'   // on mark → white
      },
  { value: '#333333' }    // off mark → dark
]
```

**Edge case — light-colored marks:**

The binary white/dark approach handles the common case (dark bars, light
background). A follow-up could compute luminance from the mark's actual
fill color for full generality, but that's out of scope for this
exploration. The binary approach matches what Tableau does.

**Success criteria:**
- [ ] Simple bar with `position: top`: label above bar is dark
- [ ] Same bar with collision pushing label inside: label turns white
- [ ] Stacked bar segments: all labels inside segments are white
- [ ] Explicit `color: "#ff0000"` in YAML overrides dynamic contrast
- [ ] Horizontal bars: same behavior

---

### Stage 6: Point/circle mark labels

**Goal:** Extend labels to point and circle marks. These use the same
mechanism as bars — each datum is an individual mark instance with its own
bounding box — so the patch function needs only a different anchor strategy.

**Files touched:**
- `shelves/translator/labels.py` — remove `is_bar_mark` gate, emit intent
  for point/circle marks
- `shelves/translator/patterns/*.py` — emit label intent for point marks
- `shelves/render/to_html.py` — add point/circle anchor strategy
- `tests/test_labels.py` — add scatter/point label tests + fixtures

**Why this is low effort:** Point marks, like bars, are one mark instance
per datum. `source: "mark_0"` gives one label candidate per point. The
only change is the anchor strategy — 8-direction candidates instead of
inside/outside.

**Anchor strategy for points:**

```js
// Points try 8 directions, prioritizing user's preferred side
case 'top':    return ['top', 'top-right', 'top-left', 'right', 'left',
                       'bottom-right', 'bottom-left', 'bottom'];
```

**Success criteria:**
- [ ] `label: true` on a scatter plot labels points, hiding in dense areas
- [ ] Bar labels still work as before
- [ ] `label: true` on line/area/pie marks is silently ignored (deferred)

---

### Stage 7: Cleanup and migration

**Goal:** Remove all old pure-VL label code paths. Pin CDN versions.
Update documentation.

**Files touched:**
- `shelves/translator/labels.py` — delete dead code (position map, etc.)
- `shelves/render/to_html.py` — pin `vega@5.x.x` and `vega-lite@6.x.x`
- `docs/guide/dsl-reference.md` — update label position docs
- `CHANGELOG.md` — document the change

**Pin versions:**

The patch relies on the structure of compiled Vega output. VL version
changes can rename internal marks/data sources. Pin to specific minor
versions:

```html
<script src="https://cdn.jsdelivr.net/npm/vega@5.30.0"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@6.1.0"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6.26.0"></script>
```

**Success criteria:**
- [ ] No dead code in `labels.py`
- [ ] `LabelPosition` is 4 values, not 8
- [ ] CDN URLs are pinned
- [ ] DSL reference docs updated
- [ ] Full test suite green
- [ ] CHANGELOG entry written

---

### Stage 8: Line/area mark labels (deferred — if needed)

**Goal:** Label line and area marks. This is fundamentally different from
bars/points and is deferred to a separate spike.

**Why it's different:** A line mark is a single path through N data points
— it's one mark instance, not N. You can't `source` from the line mark
and get per-point labels. Same for area. The patch function needs a
different sourcing mechanism: read from the **data** (not the mark),
filter to the desired points (e.g. rightmost per series), and use the
label transform for overlap avoidance.

**Typical dataviz patterns for line/area labels:**
- Label the rightmost point per series (most common — "label the line end")
- Label min/max points
- Label at regular intervals

Good data visualization rarely puts numbers on every point of a line or
area. The primary use case is series identification at the line end, which
is a different UX goal than bar/point labels.

**Rough approach (when tackled):**
1. Emit a `"markType": "line"` field in usermeta so the patch knows
2. Patch sources from the mark's data (not the mark itself)
3. Filter to the last datum per series (`argmax` on the x-field)
4. Place one label per series at the line end
5. Use the label transform for overlap avoidance between series labels

**Success criteria:**
- [ ] `label: true` on a line chart labels the rightmost point per series
- [ ] `label: true` on an area chart labels the area at the right end
- [ ] Multi-series lines: labels avoid each other
- [ ] Dense multi-series: overlapping end labels are hidden

---

## Risk log

| Risk | Mitigation |
|---|---|
| VL compiled mark names aren't stable across versions | Pin VL version; source from mark object, not field names |
| `label` transform not in `vega@5` CDN build | It's been core since v5.16 (2022). Verified in vega monorepo |
| Patch function becomes complex JS in Python string | Keep it under 80 lines; extract to a separate `.js` file if needed |
| Label-size-aware headroom (labels clipped at chart edge) | Out of scope — `label` transform hides clipped labels, which is acceptable for now |
| Performance on dense charts | Bitmap test is O(pixels), not O(marks) — scales well up to ~30k points |

---

## What this replaces

All of the following current code is deleted or rewritten:

- `LABEL_POSITION_MAP` (16-entry dict of static dx/dy)
- `_STACKED_CENTER_POSITION`
- `build_label_layer()` — the 100-line VL text layer builder
- `wrap_spec_with_label()` — the layer-wrapping helper
- `maybe_wrap_with_label()` — the bar-only gate
- `is_bar_mark()` — the mark type check
- The `__stack_mid` / `__stack_start` / `__stack_end` transform pipeline

Replaced with: `build_label_intent()` (~20 lines) + one JS patch function
(~60–80 lines).

---

## Out of scope

- **Label-size-aware headroom** — extending scale domain to fit labels.
  The `label` transform hides labels that don't fit, which is acceptable.
  Full headroom requires Vega signals feeding scale domain, which is a
  future stage.
- **Luminance-aware contrast** — computing label color from the mark's
  actual fill color. Binary white/dark overlap detection is sufficient.
- **Interactive label features** — click-to-highlight, tooltip on hover.
  These are separate Vega interaction features.
- **Line/area mark labels** — fundamentally different mechanism (data-sourced,
  not mark-sourced). Deferred to Stage 8 / KAN-287 as a separate spike.
- **Backend abstraction** — `ChartCompilerBackend` protocol. Valuable but
  independent of this change.
