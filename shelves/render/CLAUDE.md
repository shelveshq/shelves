# Render — CLAUDE.md

This module turns a Vega-Lite spec into rendered output. On this branch it owns
the **compile-then-patch label** mechanism (KAN-279) — an *exploratory* approach
(labels via a browser-side vegaEmbed `patch`) that competes with the separate
KAN-268 "implicit text-mark layer" direction. It is undecided which lands; this
doc describes compile-then-patch only.

## Files

- `to_html.py` — builds the standalone HTML page (used by the `render` and
  `dev` CLIs). Inlines `label_patch.js` and calls `vegaEmbed(..., {patch})`.
  Also exposes `load_compound_fit_js()`.
- `label_patch.js` — **the single source of truth** for browser-side label
  rendering (`window.labelPatch`). Read fresh on every render via
  `load_label_patch_js()`.
- `compound_fit.js` — browser-side sizer for **compound** Vega-Lite specs
  (`window.compoundFit`). See "Compound-spec sizing" below.

## Compound-spec sizing (compound_fit.js)

Compound specs (`vconcat`/`hconcat`/facet/repeat) don't support
`width/height:"container"`, so they can't responsively fit a box. Estimating the
per-panel pixels in Python is brittle — it needs the rendered size of axes and
titles, which depends on real text metrics we cannot measure without a browser
(swapping a stacked chart between `vconcat` and `hconcat` broke the old Python
heuristic: a y-axis reserves *width*, an x-axis reserves *height*, and each panel
also has a cross-axis measure axis).

So `compound_fit.js` measures in the browser, same split as the label patch —
**Python owns intent (emit the compound spec + the solved target box); JS owns
mechanics (measure + size)**:

1. `layout.wrap_html_page` emits the compound spec **unsized** (it keeps the
   compiler's `bounds:"flush"` + `spacing`) and records the sheet's solved
   `content_dims` in a `fitTargets` map, then calls `compoundFit.fit('#id', spec,
   box, opts)`.
2. `compoundFit.fit` does a **two-pass measure → resize → re-render**: render with
   a probe cell size, read `view.scenegraph().root.bounds` for the *real* total
   size, derive the "chrome" (axes + title + spacing, invariant to cell size),
   compute even cell sizes via the pure `computeGridFit`, then re-embed exactly.

`computeGridFit`/`solveAxis` are **pure** (no DOM): concat is a degenerate grid
(`vconcat`=rows×1, `hconcat`=1×cols), and facet/repeat pass their real `rows×cols`
— the facet grid is counted in JS from the bound `data.values` (`facetGrid`), the
repeat grid from its array lengths (`repeatGrid`). The same `withCellSizes` then
sizes either the concat panel list or the facet/repeat inner `spec.spec`. When a
facet spec carries no bound data the grid can't be counted, so `fit` degrades to
the width-only `fitFacet` fallback.

Bounds differ by kind. Concat uses `bounds:"flush"` (emitted by
`patterns/stacked.py`) so its header-less panels pack tightly and uniformly.
Facet/repeat use `bounds:"full"` instead: each cell has a header drawn *above* it,
and under `"flush"` the inter-row spacing reserves no room for it, so a row's
headers overlap the cells of the row above (the collapsed-row-gap bug). `"full"`
reserves each cell's header/axis in the layout, turning the proportionally-reduced
spacing into a clean gap. The chrome math is unchanged either way (the header is
size-invariant and cancels out of `chromeH = total − gridPlot`).

Reused like the patch: `compound_fit.js` is a plain global script, read fresh per
render, inlined by `wrap_html_page` (which serves both the CLI dashboard HTML and
the studio, whose preview renders that HTML in an `iframe.srcdoc`).

## The three render paths share ONE patch file

Labels render in the browser, not Python. The same `label_patch.js` must reach
all three pipelines or they drift:

| Path | How it gets the patch |
|---|---|
| `render` CLI | `to_html.py` inlines the file |
| `dev` CLI | same `render_html()` |
| **studio** | `server.py` serves it at `GET /label-patch.js`; `static/js/preview.js` passes `patch: window.labelPatch` to vegaEmbed |

If you change labels, **none** of these may go stale:
- It is authored as a plain global script (not an ES module) so it works both
  inlined into a `file://` page and loaded via `<script src>` in the studio.
- It is read **fresh per render**, not cached at import — so a long-running
  dev/studio server picks up edits without a restart.
- The studio's `preview.js` is a separate render path from `to_html.py`. Wiring
  labels into one does not wire the other. (This is why labels once worked in
  the CLI but were invisible in the studio.)

## How labels work

Python emits **intent** in `usermeta.shelves.labels` (one descriptor per
labelable mark, with `markName`, `field`, `format`, `vertical`/`horizontal`
side, `size`, `color`). The JS patch reads the intent, finds the named mark in
the **compiled Vega** scenegraph, and inserts a sibling `text` mark. There are
two placement paths (KAN-283):

- **Outside** (`top`/`bottom`/`left`/`right`, the default for an un-segmented
  bar): the text mark is **sourced from the bar mark** (`from: {data: <markName>}`)
  and carries a Vega `label` transform that places each label (preferred anchor →
  opposite-side fallback → hide on overlap) and writes
  `x`/`y`/`opacity`/`align`/`baseline` onto the items.
- **Inside / center** (explicit `center`, and the default for a real stacked
  segment): placed **deterministically** — band-centered on the cross axis,
  midpoint of the segment on the measure axis — and sourced from the **data**
  (`from: <mark.from>`). The `label` transform's `['middle']` anchor drops most
  stacked-segment labels (only one band survives), so center placement does NOT
  use it. Verified by PNG.
- **Point / tick** (`point`/`circle`/`square` → Vega `symbol`, and `tick` →
  `rect` role `tick`, KAN-285): one mark instance per datum, like a bar.
  Labels are **sourced from the mark** and placed by the `label` transform with
  **8-direction anchor candidates** (`pointAnchorCandidates`), leading with the
  user's preferred side. No headroom and no deterministic center path — points
  have no measure axis. `color: match` reads `enc.stroke` for unfilled points
  (which color via stroke, not fill).

> ⚠️ The `label` transform is brittle for dense bar charts: it hides labels that
> overlap a neighbor *or* spill past the plot edge, so even a 4-bar chart can
> lose most of its outside labels. This is a known limitation kept on purpose
> for now; a future theme token may gate the aggressive auto-hide. Always verify
> label changes by **rendering a PNG and looking** — never trust the scene walk.

Design principle (keep it this way): **Python owns intent; JS owns mechanics.**
Do not gate by mark type in Python — emit intent for all labelable marks and let
the JS patch decide what renders. That keeps future point/line support (KAN-285,
KAN-287) as JS-only changes.

## Compiled-Vega gotchas (these caused real bugs — read before editing the patch)

The patch operates on **compiled Vega**, not the Vega-Lite spec. The structure
is surprising in ways that have repeatedly broken labels:

1. **Mark naming.** VL compiles `name: "mark_0"` on a unit spec into a Vega mark
   named `"mark_0_marks"`. `findMarkPath` matches both `name` and `name+'_marks'`.

2. **Bars and ticks are BOTH `rect`.** Mark `type` does not distinguish them.
   VL tags them via `encode.update.ariaRoleDescription.value` (`'bar'` vs
   `'tick'`). The patch labels bars only by skipping rects whose role is not
   `'bar'` (allowing rects with no role).

3. **Labels are sourced FROM the bar mark, not the data.** The text mark's
   `from.data` is the compiled bar mark name (`mark.name`, e.g. `"mark_0_marks"`),
   so each text datum is a bar **scene item**. Its backing tuple is at
   `datum.datum` — read the measure as `datum.datum['<field>']` and the
   match-color field as `field: 'datum.<field>'`. (Reading `datum['<field>']`
   silently yields undefined — this was the field-access trap.)

4. **Stacked/rounded bars live in a clipped facet "stack group".** VL wraps them
   in a group with `clip:{value:true}` sized to the bar's bounding box (to round
   the stack's outer corners). A label at the bar tip is **clipped away**. The
   patch drops `clip` on any faceted ancestor of a labeled bar. (This was the
   "bar labels render nowhere" bug.)

5. **VL stack-encodes even single bars.** A plain single bar still compiles to
   `y:{field:"x_end"}, y2:{field:"x_start"}` with `start = 0`. So "is this
   stacked?" (distinct start/end fields) is **true for every bar** — you cannot
   use it to detect a *real* multi-segment stack. The measure segment value is
   `end - start` (correct for single bars too, since start = 0).
   **A custom `label.field` short-circuits this.** When the intent's `field`
   differs from the bar's measure (derived by stripping the `_start`/`_end`
   suffix off the position field), the label reads that column **raw**
   (`datum.datum['<field>']`) instead of `end - start`. Without this, a custom
   field is ignored and the bar's measure value is shown instead (the
   `label_bar_custom_field` regression).

6. **The `label` transform `size` is NOT `[width, height]`.** That works only
   for a top-level unit spec. In **concat/faceted** layouts there is no
   top-level `width`/`height` signal (the child group carries `childWidth` /
   `mark_0_height` etc.), so `[width, height]` resolves to 0 and `vega-label`
   throws `IndexSizeError: source width is 0` — the whole chart fails to render.
   `labelSizeSignal(path)` walks up to the nearest non-facet ancestor group and
   reads its width/height, falling back to `[width, height]` for a unit spec.
   The transform also mutates scene items in place, so the outside text
   `encode.update` sets only `text`/`fontSize`/`fill` — never position.

7. **A real stack defaults to inside-center; a plain bar defaults to outside.**
   `isSegmented` = the bar has a `fill` bound to a field **different** from the
   band/category field (`enc.fill.field !== bandField`). Charter has no grouped
   (xOffset) bars, so fill≠band ⟹ a true multi-segment stack — those default to
   `center` (deterministic, inside each segment) because the outside anchor only
   fits the outermost segment. An un-segmented bar defaults to `top` (vertical) /
   `right` (horizontal), placed by the `label` transform. `anchorCandidates()`
   maps an explicit outside side to `[primary, fallback]`
   (`top`→`['top','bottom']`, etc.); explicit `center` is deterministic (see
   "How labels work").

8. **Scale headroom for edge labels (KAN-289).** A label at a bar tip/end is
   clipped because the measure scale domain fits the data exactly. The patch
   expands it via `applyHeadroom()`. Two traps make this non-obvious:
   - **The scale is named `mark_0_y` / `mark_0_x`, not `y`/`x`.** VL names
     unit-spec scales `<markName>_<axis>`. Read the name from the mark's own
     encoding (`enc.y.scale`), never hardcode `'y'`.
   - **The domain is data-driven (`{data, fields}`), not a `[min,max]` array.**
     You cannot multiply a number. `applyHeadroom` adds an `aggregate` data
     source (`<scale>_hr`) computing the field extent, exposes
     `<scale>_dmax`/`_dmin` signals, and sets `scale.domainMax`/`domainMin` to
     a signal adding `factor * span`. The factors live in the `HEADROOM`
     constant at the top of `label_patch.js` (default 0.12 horizontal, 0.10
     vertical) — tweak there.
   It only touches **top-level linear scales** whose domain data is also
   top-level (concat/grouped keep both top-level; true faceting nests them and
   is skipped). It is idempotent per scale via the `<scale>_hr` name guard, and
   runs only for labeled bars, so non-labeled charts are unaffected. `nice:true`
   rounds the expanded endpoint further outward — that is expected (more room,
   never less), so assertions on the new domain must use inequalities.

## Verifying browser-rendered output (labels and sizing)

Python tests cannot see browser output, and the Vega **scenegraph `item.bounds`
are group-local in faceted layouts** — they will lie to you (bars and labels can
appear stacked at y≈0 when they actually render distributed). Do not trust a
scene walk for position. Verify in a **real browser** and look:

- **Labels / single charts:** `python -m shelves.cli.render <chart>.yaml
  --data ...` (or `shelves.cli.dev` for live reload) → open the HTML in a
  browser and screenshot. To locate where labels land, temporarily paint them
  red/large in a copy of the patch.
- **Dashboards / compound sizing:** `python -m shelves.cli.render <dashboard>.yaml`
  (or the studio preview, which renders the same HTML in an `iframe.srcdoc`) →
  screenshot. Check both `vconcat` and `hconcat` (swap a stacked chart's
  `rows`/`cols`): even cells, no axis/title clipping, fits the canvas.

There is **no node/canvas PNG harness** — it is intentionally avoided to keep the
repo free of node/npm dependencies. The only JS that runs under node is the pure
sizing math in `compound_fit.js`, exercised by **`node --test
shelves/render/compound_fit.test.js`** (node's built-in runner, zero deps). DOM
measurement in `compoundFit.fit` is browser-only and is checked by the manual
screenshots above.
