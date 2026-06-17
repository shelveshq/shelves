# Render — CLAUDE.md

This module turns a Vega-Lite spec into rendered output. On this branch it owns
the **compile-then-patch label** mechanism (KAN-279) — an *exploratory* approach
(labels via a browser-side vegaEmbed `patch`) that competes with the separate
KAN-268 "implicit text-mark layer" direction. It is undecided which lands; this
doc describes compile-then-patch only.

## Files

- `to_html.py` — builds the standalone HTML page (used by the `render` and
  `dev` CLIs). Inlines `charter_patch.js` and calls `vegaEmbed(..., {patch})`.
- `charter_patch.js` — **the single source of truth** for browser-side label
  rendering (`window.charterPatch`). Read fresh on every render via
  `load_charter_patch_js()`.

## The three render paths share ONE patch file

Labels render in the browser, not Python. The same `charter_patch.js` must reach
all three pipelines or they drift:

| Path | How it gets the patch |
|---|---|
| `render` CLI | `to_html.py` inlines the file |
| `dev` CLI | same `render_html()` |
| **studio** | `server.py` serves it at `GET /charter-patch.js`; `static/js/preview.js` passes `patch: window.charterPatch` to vegaEmbed |

If you change labels, **none** of these may go stale:
- It is authored as a plain global script (not an ES module) so it works both
  inlined into a `file://` page and loaded via `<script src>` in the studio.
- It is read **fresh per render**, not cached at import — so a long-running
  dev/studio server picks up edits without a restart.
- The studio's `preview.js` is a separate render path from `to_html.py`. Wiring
  labels into one does not wire the other. (This is why labels once worked in
  the CLI but were invisible in the studio.)

## How labels work

Python emits **intent** in `usermeta.charter.labels` (one descriptor per
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
   use it to detect a *real* multi-segment stack. The segment value is
   `end - start` (correct for single bars too, since start = 0).

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
     constant at the top of `charter_patch.js` (default 0.12 horizontal, 0.10
     vertical) — tweak there.
   It only touches **top-level linear scales** whose domain data is also
   top-level (concat/grouped keep both top-level; true faceting nests them and
   is skipped). It is idempotent per scale via the `<scale>_hr` name guard, and
   runs only for labeled bars, so non-labeled charts are unaffected. `nice:true`
   rounds the expanded endpoint further outward — that is expected (more room,
   never less), so assertions on the new domain must use inequalities.

## Debugging the patch: render to PNG and LOOK

Python tests cannot see browser output, and the Vega **scenegraph `item.bounds`
are group-local in faceted layouts** — they will lie to you (bars and labels can
appear stacked at y≈0 when they actually render distributed). Do not trust a
scene walk for position. The reliable harness:

1. `compile_chart(...)` → write the VL spec (give panels fixed `width`/`height`;
   `'container'` sizing has no DOM in node and collapses facets).
2. `npx -p vega-lite@6 -p vega vl2vg spec.json > vg.json` (VL → Vega).
3. In node: load `vg.json`, run `charterPatch` (set `globalThis.window` then
   `new Function(fs.readFileSync('charter_patch.js'))()`), then
   `new vega.View(vega.parse(vg), {renderer:'canvas'})` → `view.toCanvas()` →
   write a PNG (needs the `canvas` package). **Read the PNG and look at it.**
4. To locate where labels land, temporarily paint them red/large in a copy of
   the patch.

PNG ground truth is what caught every bug above after scenegraph inspection
sent us in circles.
