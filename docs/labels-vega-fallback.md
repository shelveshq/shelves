# Data Labels & the Vega Fallback — Design Discussion

> Status: exploration / decision memo (not yet implemented)
> Context: Charter currently compiles its Tableau-inspired DSL to **Vega-Lite**.
> Driver: data labels (and, looking ahead, filters/interactions) are fighting
> Vega-Lite's high-level abstraction. This memo captures the investigation and
> the recommended path.

---

## 1. The starting question

> "Is there a better backend for my DSL, or should I accept Vega-Lite's limitations?"

### Key diagnosis: most current pain is self-imposed, not Vega-Lite's ceiling

- **Labels** — `shelves/translator/labels.py` hardcodes `_BAR_MARK_TYPES = {"bar"}`
  and bails on everything else. That's *our* restriction. Vega-Lite renders text
  marks on any geometry via layering; line/area/scatter labels are doable today.
- **Interactive filters** — our own docs say interactivity is *"deferred to a
  future revision."* Vega-Lite already supports dropdown/slider/range filters via
  `params` + `select` + `bind: {input: ...}`, and cross-filtering via shared
  params across a `concat`. We haven't hit a wall; we haven't built it yet.

Where Vega-Lite **genuinely** bites later:
- **Label placement** — VL's auto-layout is coarse; we already hand-tune `dx/dy`.
  Collision-aware, data-driven label layout is real work in VL.
- **Bespoke interactions** beyond selections (custom cross-chart actions,
  "use as filter," linked KPI tiles) get awkward.
- **Performance** — our docs peg the comfortable ceiling at ~10k points,
  sluggish past ~30k.

### Coupling reality (why a pivot is expensive but the DSL is portable)

| Layer | Coupling to Vega-Lite | Reusable on a pivot? |
|---|---|---|
| Schema / DSL (`schema/`) | Low — Tableau-inspired | ✅ Mostly keep |
| `FieldTypeResolver` / data binding | Abstracted via protocol | ✅ Keep |
| Translator (`translator/`, ~3,200 lines) | **Very high** | ❌ Rewrite |
| Theme merge (`theme/merge.py`) | High (VL `config`) | ❌ Rewrite |
| Render (`render/to_html.py`) | 100% `vegaEmbed` | ❌ Rewrite |

The DSL was designed Tableau-first, so it's portable. But ~2,500+ lines of
translator/theme/render are a from-scratch rewrite **per backend**.

---

## 2. Backend options that were surveyed

| Option | Fit | Notes |
|---|---|---|
| **Full Vega** (not VL) | **Lowest-friction pivot** | Same ecosystem, same `vegaEmbed`, same JSON-spec philosophy. Adds `signals` and the `vega-label` transform — our two pain points. Cost: specs are ~an order of magnitude more verbose. |
| **Apache ECharts** | Best for rich interaction/dashboards | Native zoom/brush/cross-filter, strong labels, scales to large data, very well maintained. Config-object model, further from our grammar. |
| **AntV G2** (v5.4.8, Jan 2026) | Closest philosophical match | Grammar of graphics **and** of interactions. Smaller Western community than ECharts. |
| **Observable Plot** | Pass | Weaker interactions than VL; no polar/arc (no pie). Wrong direction if interactivity is the goal. |
| Plotly.js | No compelling edge | Config model like ECharts with less compositional grammar. |

**Recommendation at this stage:** don't hard-pivot. Exhaust Vega-Lite first,
introduce a backend seam for optionality, and keep **full Vega** as the
designated escape hatch (reuses renderer, ecosystem, spec-generation philosophy).

---

## 3. Can we "escape-hatch" Vega into Vega-Lite?

**No.** The relationship is strictly **one-directional**: Vega-Lite *compiles
down to* Vega. There is no `{"vega": ...}` block, no raw-mark passthrough — you
cannot sprinkle Vega primitives inside a VL spec.

**But** you can fall back to Vega *at the boundary* via **compile-then-patch**:
- `vega-embed` has a `patch` option that runs against the **compiled** Vega
  (after VL lowers the spec). VL stays the authoring layer; you inject label
  marks / transforms into the Vega output.
- `vegaEmbed` auto-detects VL vs Vega by `$schema`, so it renders either.
- Our `render/to_html.py` already loads `vega@5`, `vega-lite@6`, `vega-embed@6`.

```js
vegaEmbed('#chart', spec, {
  renderer: 'canvas',
  patch: (vgSpec) => {
    // vgSpec is the compiled Vega — add label transform / text marks here
    return vgSpec;
  },
  actions: { ... }
});
```

> Note: there is **no maintained Python VL→Vega compiler** (`vl.compile` is
> JS-only). So compile-then-patch happens **at render time in the browser**, not
> in Python. Our Python pipeline keeps emitting Vega-Lite.

---

## 4. How position-aware labels work in Vega (`label` transform)

The `label` transform uses a **rasterized occupancy bitmap** (not constraint
solving / force simulation):

1. Existing marks are rasterized onto a 1-bit-per-pixel grid (occupied vs free).
2. Each label gets a **priority-ordered list of candidate positions** from the
   `anchor` / `offset` arrays.
3. Each candidate is tested against the bitmap via **bitwise AND**; first
   non-colliding candidate wins.
4. Placed labels are OR'd back into the bitmap, so the next label sees them.
5. If **no candidate fits → `opacity: 0`** (hidden, not removed). You get back
   `originalOpacity` / `transformed` fields.

Overlap-test cost is fixed by chart + label size, **independent of mark count** —
which is why it scales to dense scatterplots. `sort` controls label priority.

### The three scenarios

| Need | Handled? | Mechanism |
|---|---|---|
| Inside↔outside bar fallback | ✅ | Ordered `anchor`/`offset` candidates; tries outside, falls to inside on collision, flips `align`/`baseline` automatically |
| Drop label overflowing a stacked segment | ✅ | No candidate fits → `opacity: 0`. Per-label, geometry-driven |
| Scatter overlap avoidance | ✅ | 8-direction candidates + running bitmap; hide on dense clusters; `sort` sets priority |
| **Label-size-aware headroom** | ❌ | **Not done by the transform** — see below |

### Headroom — the honest gap

The `label` transform is strictly **place-or-hide within existing pixel space**.
It will never expand the chart or extend a scale domain to make room. `padding`
only lets a label *overflow* its mark's box by N px; it doesn't resize anything.

So "there are outside-top labels, extend the y-axis so they don't clip" is
**not** something the transform does — an outside-top label that runs past the
edge just gets **hidden**. That headroom logic stays upstream and must be
label-size-aware (measure text → set scale domain / padding). This is a concrete
point in favor of **full Vega**, where a text-size signal can feed the scale
domain in the same spec.

---

## 5. The stacked-segment label bug (the `size/2` issue)

**Symptom:** labels land on the wrong segments of stacked bars.

**Root cause:** we compute the stack **twice, with two different orderings**:
- bars get positions from VL's `stack` transform (**sorted**);
- text gets positions from a *parallel* `size/2` computation assuming **DB row
  order**.

Two sources of truth → they drift → labels mis-align. Any fix that keeps two
parallel computations stays fragile.

### Two ways out

**(A) Best — stop computing midpoints in data space.** Let the Vega `label`
transform place text relative to each **rendered segment rect's geometry**
(center anchor, `avoidBaseMark: false` to sit inside). No data join, no parallel
sort, no `size/2` — the label sits at the visual center of whatever rect VL
actually drew, in whatever order it drew it. The mismatch becomes structurally
impossible, and **small segments auto-hide for free**.

**(B) If staying in pure VL — single-source the stack.** Derive the text `y`
from the **same** `aggregate` + `stack` + `order` encoding the bars use, and
center with VL's stacked-label centering (`bandPosition: 0.5` on the stacked
field) instead of a hand-rolled `size/2`. Same stack transform, same order →
cannot diverge.

**Through-line:** stop recomputing in data space what the renderer already
computes in geometry space.

---

## 6. The three primitives Vega-Lite hides (and Vega exposes)

The struggle in pure VL is the abstraction doing its job. Each thing maps to a
native Vega primitive VL doesn't surface. **All three ship in the standard
`vega@5` CDN build** — the `label` transform has been core since **v5.16** (the
old `vega-label` repo was folded into the Vega monorepo). No separate install or
`registerTransform`.

| Capability | Native Vega primitive | Why VL can't |
|---|---|---|
| Geometry-based labels (flip + overlap-hide) | **Reactive geometry** — a dataset `source`d from a mark + `label` transform | VL exposes no user-facing reactive geometry; you can't point a text layer at the rendered bars |
| Stacked-segment centering | **Explicit `stack` output** (`y0`/`y1`) + `formula` for midpoint | VL computes the stack internally; never hands you a clean joinable `y0`/`y1` |
| Label-size-aware headroom | **Signals** driving `domainMin`/`domainMax`/padding | VL hides signals entirely |

```js
// 1. geometry-based labels
{ "name": "barLabels", "source": "bars",
  "transform": [{ "type": "label",
                  "size": [{"signal":"width"},{"signal":"height"}],
                  "anchor": ["top","bottom"], "offset": [4,-4] }] }

// 2. stacked-segment centering (only needed if hand-authoring Vega)
{ "type": "stack", "groupby": ["category"], "field": "value", "sort": {...} },
{ "type": "formula", "as": "yc", "expr": "(datum.y0 + datum.y1) / 2" }

// 3. headroom
{ "name": "yScale", "type": "linear", "range": "height",
  "domainMax": {"signal": "maxBarTop * 1.12"} }
```

**Cost of the fallback:** a ~15-line VL chart becomes ~60–100 lines of Vega
(explicit scales/axes/data pipeline). Translator complexity rises for these
chart types. That's the real price.

---

## 7. On the proposed "flip then remove overlaps" plan

Original idea: pick a side in the DSL, then in Vega (1) flip alignment if the
label bleeds over the axis, (2) check overlap and remove overlapping ones.

**Verdict:** that's reimplementing the `label` transform as a fixed **two-pass**
pipeline — and strictly weaker. The two steps map directly onto the transform:
- "flip if it bleeds" = a **second candidate** in `anchor`/`offset`; boundary
  bleed-detection is automatic via `size`.
- "remove overlaps" = the default **hide-on-no-fit**, tested against a *running*
  bitmap (handles label-label overlap too), with `sort` deciding priority.

The fixed two-pass shape (flip first, then dedupe) loses the interleaving: a
flipped label can collide with something it wouldn't have, and you kill it when
the right answer was a different anchor. Let the transform interleave
candidates × overlap per label.

**Trade-off to weigh:** the transform optimizes *global legibility* at the cost
of *per-label determinism*. If the DSL must guarantee a side, constrain that
label's candidate list (single anchor, no fallback); otherwise let it optimize.

---

## 8. Recommended architecture — compile-then-patch (no pipeline rewrite)

**You do not redo the pipeline.** Keep Python emitting Vega-Lite **without**
labels. The compiled Vega already contains the scales, axes, and bar marks — you
append one label dataset + one text mark on top. Labels really are "just text."

How each capability lands on this approach:

| Capability | On compile-then-patch |
|---|---|
| #1 Flip + overlap-hide | ✅ Clean — exactly what `patch` is for |
| #2 Segment centering | ✅ Clean — geometry-based, so the `size/2` sort bug never arises (no stack-midpoint math needed) |
| #3 Label-size-aware headroom | ⚠️ Awkward — needs to edit the generated scale domain + has a circular dependency (domain ↔ label sizes). **Approximate** now (bump `domainMax` by a multiplier / reserve fixed top fraction); full version is what would eventually justify hand-authored Vega |

### The clean seam

- **Compile + patch run at render time in the browser** (in `to_html.py`'s
  script). Python pipeline stays VL.
- Pass DSL label **intent** (side, priority) across the boundary via VL's
  top-level **`usermeta`** block — VL copies it untouched into compiled Vega.
  The JS patch reads `usermeta` and builds the label layer.
- Division of labor: **DSL/Python owns label *intent*; one reusable JS patch
  owns label *mechanics*.** No second emitter, no hand-authored axes, fully
  reversible.

### Caveat

The patch locates the bar mark in compiled output to source labels from it. VL's
generated **internal field names** can shift between versions — source from the
**mark** (stable-ish), not from VL's internal stacked field names (brittle).
**Pin the `vega-lite` version.**

---

## 9. Recommended next steps

1. **Exhaust Vega-Lite first** where cheap: un-hardcode `labels.py` to layer text
   on any mark; build the deferred `params`/`bind` interactive-filter path. Find
   out whether VL's *ceiling* is really the problem.
2. **Build the compile-then-patch seam** for labels: VL emits `usermeta` label
   intent → small reusable JS patch compiles, adds the `label`-transform text
   layer, and does approximate headroom. Prototype on one stacked-bar fixture and
   confirm the sort bug is gone.
3. **Add a backend seam for optionality** (a `ChartCompilerBackend` protocol +
   an IR between `ChartSpec` and the spec dict), mirroring the existing
   `FieldTypeResolver` pattern. Cheap now; makes any future swap incremental.
4. **Keep full Vega as the designated escape hatch** — only the
   label-size-aware *headroom* case is likely to force hand-authored Vega; the
   rest is reachable via patch.

---

## Appendix — references

- Vega `label` transform: https://vega.github.io/vega/docs/transforms/label/
- `vega-label` (now in the Vega monorepo): https://github.com/vega/vega/tree/main/packages/vega-label
- Occupancy-bitmap labeling (UW IDL): https://idl.cs.washington.edu/files/2021-FastLabels-VIS.pdf
- Legible Label Layout (algorithm + VL integration): https://arxiv.org/abs/2405.10953
- vega-embed (`patch` option): https://github.com/vega/vega-embed
- Compiling Vega-Lite to Vega: https://vega.github.io/vega-lite/usage/compile.html
- AntV G2: https://g2.antv.antgroup.com/en
- Apache ECharts: https://echarts.apache.org/en/feature.html
- Plot vs Vega-Lite: https://observablehq.com/@observablehq/plot-vega-lite
