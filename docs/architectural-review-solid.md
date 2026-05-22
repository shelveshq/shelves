# Architectural Review — `shelves`

**Date:** 2026-05-22  
**Branch:** `claude/architecture-review-solid-KHPtC`  
**Scope:** ~5,800 LOC across `schema`, `translator`, `data`, `models`, `theme`, `render`, `compose`, `studio`, `cli`

## Headline

The pure compilation pipeline (parse → translate → theme → bind → render) is well-factored at the package level, but **three structural problems dominate the rest**:

1. `studio/server.py` is a 799-LOC god module that re-implements the pipeline a third time.
2. The translator's pattern handlers (`single`/`stacked`/`layers`) duplicate ~40% of their encoding logic.
3. `cube_client.py` mixes HTTP transport, query DSL, response shaping, and ChartSpec walking in one file with no abstraction seam.

Layered exception handling is the secondary concern: 19 broad `except Exception` blocks in `studio/server.py`, several silent swallows in `terminal.py`/`watcher.py`, and `loader.py`/`bind.py` let `pydantic.ValidationError` and `yaml.YAMLError` escape unwrapped.

---

## 1. SOLID — Top Violations

### 1.1 Single Responsibility

| Module | LOC | Concerns bundled | Why it hurts |
|---|---|---|---|
| `studio/server.py` | 799 | FastAPI app factory, `ConnectionManager` (66–104), lifespan (106–152), chart compile pipeline (155–225), dashboard compile pipeline (238–281, re-implemented again at 642–710), HTTP routes (503–639), PTY terminal handler (380–492), file-tree + path-traversal guard (752–795), component-tree visualizer (712) | Cannot test any one piece without spinning the whole stack; every new route bloats the file; same `parse_chart → translate_chart → merge_theme → resolve_data` chain appears at lines 204, 526, 693. |
| `data/cube_client.py` | 376 | env-var config (50–75), HTTP+auth (364–371), Cube DSL build (220–266), filter translation (269–305), response parsing (311–326), **ChartSpec walking** (81–202) | ChartSpec field collection is pure domain logic — testing it requires mocking `httpx`. Adding DuckDB/Postgres means rewriting the file. |
| `translator/layout_solver.py` `_resolve_children` | 84–294 (~210 lines) | Gap subtraction, margin computation, bucket classification (pct/px/auto), three failure modes (under-, proportional-shrink, full-shrink) each with their own warning emission | One function with three exit strategies; each branch hides what it actually changed. Hard to unit-test the overconstrained-shrink path in isolation. |
| `translator/layout.py` `render_node` | 130–223 | If/elif over 8 component types (Root, Container, Sheet, Text, Button, Link, Image, Blank), each with template + CSS merging + escaping inline | Adding a component requires touching the same hot function; type-specific rules tangle with recursion. |
| `models/resolver.py` `ModelResolver` | 318 LOC | Field parsing, type resolution, label/format/time-unit metadata, grain validation/mapping (with a `GRAIN_TO_TIME_UNIT` dict duplicated in `cube_client.py:26`) | Any alternative metadata source (dbt, Looker) must duplicate grain logic. |

### 1.2 Open/Closed

- **Filter operators** (`schema/chart_schema.py:116-156`): `_validate_operator_and_values` switches on 9 operators in one method. Adding a new operator edits the validator.
- **Leaf component types** (`schema/layout_schema.py:220-228`): the `_LEAF_BUILDERS` dict is closed; new types require edits in three places (dict + `KNOWN_LEAF_TYPES` + the model).
- **Pattern routing** (`translator/translate.py:33-65`): `isinstance(spec.rows, list)` chooses single vs. stacked vs. layers. A new pattern means editing the router rather than registering a compiler.
- **Theme preset color resolution** (`theme/merge.py:66-73`): only `text.*` is recognised. Hardcoded `getattr` lookup; can't add `brand.*` or `chart.*` without code edits.
- **Data sources** (`data/bind.py:68-72`): `if model.source.type == "cube"` is the only dispatch — no `DataSourceAdapter` protocol.

### 1.3 Liskov / Interface Segregation / Dependency Inversion

- `field_types.py:15-35` defines a clean `FieldTypeResolver` Protocol — but `translate.py:52` instantiates the **concrete** `ModelResolver(model)` directly, defeating DIP. Test doubles need monkey-patching.
- `layout_flatten.py:48-95` `_merge_style_onto_component` accepts `comp: Any` and calls `.model_copy()` / inspects `model_fields`. There is no `PydanticComponent` Protocol — passing a non-Pydantic object yields `AttributeError` instead of a typed error.
- `cube_client.py:367` hardcodes `httpx.Client(timeout=30.0)` — no transport seam, so retries, mocks, and custom headers all require source edits.

---

## 2. Duplication & Cohesion

### 2.1 The pipeline is implemented three times

`parse_chart → translate_chart → merge_theme → resolve_data → render_html` appears verbatim (with cosmetic variation) at:

- `cli/dev.py:112-141`
- `cli/render.py:90-134`
- `studio/server.py:204-225` (chart) **and** `studio/server.py:526-547` (compile-yaml route) **and** `studio/server.py:693-710` (dashboard inner)

Each site re-imports the same modules at function scope. **Fix:** introduce `shelves/pipeline.py` with two pure functions returning a `PipelineResult`:

```python
def render_chart_pipeline(yaml_text: str, *, theme_path=None, models_dir=None, rows=None) -> PipelineResult: ...
def render_dashboard_pipeline(dashboard_yaml: str, *, chart_dir, theme_path=None, models_dir=None) -> PipelineResult: ...
```

All three CLIs become 5-line wrappers; the studio routes broadcast the result.

### 2.2 Pattern handlers share too much

| Concern | `stacked.py` | `layers.py` | Status |
|---|---|---|---|
| Mark resolution cascade | `_resolve_mark` 128–134 | `_resolve_mark` 473–489 | **Identical, copy-pasted** |
| Property cascade (color/size) | inline | `_resolve_property` 454–470 | Should live in shared `resolution.py` |
| Shared-axis suppression | `_suppress_shared_axis` 57–66 | inlined 176–181 | Re-implemented |
| Panel encoding (x/y/color/detail/size/tooltip/sort) | `_compile_concat` 225–261 | `_build_simple_panel` 328–360 | ~90% overlap |

**Fix:** Create `translator/resolution.py` for cascades and `translator/panel.py` for `build_panel_encoding(entry, shared_enc, resolver, ...)`. Layers and stacked become thin orchestrators.

### 2.3 Encoding injection scattered

`encodings._auto_inject_from_model` (201–241) bundles title, format, and grid injection. Callers at `encodings.py:64`, `:76`, `stacked.py:175,226`, `layers.py:332,406` repeat the same call pattern. Split into three single-purpose injectors and provide one `build_field_encoding_with_meta(...)` helper.

### 2.4 Field collection lives in two walks

`cube_client._collect_chart_fields` (81–202) and `cube_client.build_cube_query` (220–266) both recurse through `spec.rows/cols/color/detail/...`. Any new field-bearing property in `ChartSpec` requires editing both. Extract a `ChartSpecFieldVisitor` (or a single generator) and consume it in both places.

### 2.5 `GRAIN_TO_TIME_UNIT` duplicated

Defined identically at `models/resolver.py:26-32` and `data/cube_client.py:26-32`. Move to `shelves/schema/temporal.py` and import from there.

---

## 3. Exception Handling

### 3.1 Hot-spots

26 broad `except Exception` blocks in the codebase:

| File | Count | Notable lines |
|---|---|---|
| `studio/server.py` | 19 | 96, 214, 226, 270, 456, 458, 471, 484, 522, 527, 533, 540, 548, 612, 660, 674, 701, 704, 763 |
| `compose/dashboard.py` | 2 | 77, 162 |
| `studio/terminal.py` | 2 | 171, 175 |
| `studio/watcher.py` | 2 | 68, 72 |
| `cli/dev.py` | 1 | 95 |

**The dangerous pattern:**

```python
# studio/server.py:214
except Exception as e:
    warnings.append(f"Data resolution skipped: {e}")
```

A `TypeError` from a deployment bug becomes a yellow warning to the user — operators see a healthy server. The same `Exception → broadcast` pattern at line 226 hides `ModuleNotFoundError`. At minimum, distinguish: `ValidationError` (user error, send to client) vs. everything else (log at `ERROR` and re-raise or surface visibly).

```python
# studio/server.py:443-459 (PTY _read_loop)
except Exception:
    pass
```

Silent swallow with no logging — PTY death is invisible to both browser and operator.

### 3.2 Unwrapped errors at boundaries

- `models/loader.py:67-68` — `yaml.safe_load` and `DataModel.model_validate` surface raw `YAMLError` / `ValidationError` instead of `f"Invalid model YAML in {path}: …"`.
- `data/bind.py:74-77` — generic `ValueError` instead of a typed `NoDataSourceError`. Callers can't catch selectively.
- `data/cube_client.py:370-371` — single `CubeQueryError` for HTTP 4xx, 5xx, and timeouts; no truncation of `response.text` (multi-MB error pages possible); `httpx.TimeoutException` propagates as a generic exception, not a `CubeTimeoutError`.
- `translator/filters.py:38-41` — `_translate_filter` calls `resolver.resolve_base_field(...)` without checking for `None`; failure path crashes with `AttributeError` instead of a meaningful `ValueError`.
- `translator/patterns/layers.py:225-231` — `_resolve_mark` raises with no entry/layer index in the message; debugging multi-layer charts means binary-searching the YAML.

### 3.3 Resource leaks

- `cli/dev.py:295-305` — `HTTPServer` only closed in the `KeyboardInterrupt` arm; any other exception during `serve_forever()` setup leaks a port. Wrap in `contextlib.closing(...)` or `try/finally`.
- `studio/terminal.py:103-151` — `loop.remove_reader()` is called twice defensively because of a cancellation race, pointing at missing structured cancellation around `add_reader` / `remove_reader`.

---

## 4. Security

### 4.1 DOM-XSS in `render/to_html.py:46`

```python
return f"""...
const spec = {spec_json};
..."""
```

The title is escaped (line 21), but the entire `spec_json` is interpolated raw into a `<script>` block. Two concrete attack paths:

1. A `</script>` substring in any spec string field (e.g., a tooltip caption) breaks out into HTML context.
2. Vega-Lite tooltip channels render strings as DOM under `tooltip: {format: "html"}` configurations.

In a local-dev tool the blast radius is small, but the moment dashboards are served publicly (Phase 6) this is a real DOM-XSS vector.

**Fix:**

```python
spec_json = json.dumps(spec).replace("</", "<\\/")
```

Or embed via `<script type="application/json" id="spec">` and parse client-side.

### 4.2 What's good

- `studio/server.py:752-769` `_resolve_safe` correctly uses `Path.resolve()` + `is_relative_to()` — path-traversal defence is solid.
- Terminal auth token uses `secrets.token_urlsafe(32)` + `secrets.compare_digest` with an Origin allowlist (lines 321, 416–432). Well done.

---

## 5. Test Coverage Gaps

26 test files, well-organised. Modules with **no dedicated tests**:

- `cli/render.py`, `cli/dev.py`
- `schema/field_types.py`
- `studio/terminal.py`, `studio/watcher.py`
- `theme/merge.py` (only `theme_schema` is tested)
- `translator/encodings.py`, `translator/layout_styles.py`, `translator/sort.py`
- `translator/patterns/single.py` (stacked + layers are tested)

Coverage threshold is 75% globally (`pyproject.toml:55`) but there is no per-module floor — the studio subsystem with its 19 broad `except` blocks could be at 0% and still pass CI.

---

## 6. Tooling Gaps

- `[tool.ruff]` only sets `line-length = 100`. No `lint.select` — only the default ruleset (`E`, `F`) runs. Recommended minimum: `["E", "F", "W", "I", "B", "UP", "C4", "SIM", "RUF"]`.
- No `pytest-timeout` or flakiness detection.
- No per-module coverage reporting.
- Single TODO in the codebase (`translator/layout.py:248`) — discipline is otherwise excellent.
- 4 `# type: ignore` total, 0 `cast()` calls — type discipline is genuinely strong.

---

## 7. Prioritised Refactor Plan

### Tier 1 — Structural (1–2 day items)

| # | Action | Files | Payoff |
|---|---|---|---|
| 1 | Extract `shelves/pipeline.py` with `render_chart_pipeline` + `render_dashboard_pipeline`. Replace pipeline sequences in `cli/render.py:90`, `cli/dev.py:108`, `studio/server.py:155`/`238`/`642`. | new file + 3 call sites | Removes ~150 LOC of duplication; one place to change for new pipeline stages. |
| 2 | Split `studio/server.py` into `studio/connection.py`, `studio/lifespan.py`, `studio/terminal_handler.py`, `studio/routes/{files,compile,dashboard,terminal}.py`. Server becomes a thin app factory (~80 LOC). | `studio/` | Each piece becomes testable; the 19 broad excepts become 4–5 narrow ones with `logger.exception`. |
| 3 | Extract `translator/resolution.py` (mark + property cascades) and `translator/panel.py` (`build_panel_encoding`). Have `stacked.py` and `layers.py` import them. | `translator/patterns/` | Removes ~200 LOC; `_resolve_mark` lives in one place. |

### Tier 2 — Abstraction seams (half-day items)

| # | Action | Files |
|---|---|---|
| 4 | `DataSourceAdapter` protocol in `data/sources.py`; `cube` registers itself; `bind.py:68-72` does a registry lookup. | `data/` |
| 5 | Extract `HTTPTransport` Protocol + `CubeHTTPTransport` from `cube_client.py:367`; inject into `fetch_from_cube_model`. Test with `respx`. | `data/cube_client.py` |
| 6 | Move `GRAIN_TO_TIME_UNIT` to `shelves/schema/temporal.py`; delete both duplicates. | `models/resolver.py:26`, `data/cube_client.py:26` |
| 7 | Wrap loader IO: `yaml.safe_load` + `DataModel.model_validate` → `ValueError(f"… in {path}: {e}") from e`. Same pattern for `chart_schema.parse_chart`. | `models/loader.py:67`, `schema/chart_schema.py` |

### Tier 3 — Local cleanups (≤1 hour each)

| # | Action | Files |
|---|---|---|
| 8 | Escape `</` in `spec_json` before HTML interpolation. | `render/to_html.py:46` |
| 9 | Classify Cube HTTP errors: `CubeAuthError` (401/403), `CubeServerError` (5xx), `CubeTimeoutError`, with truncated `response.text`. | `data/cube_client.py:370` |
| 10 | Replace `if/elif` over 8 component types with a `RENDERERS: dict[type, Callable]` dispatch. | `translator/layout.py:130` |
| 11 | Add `if field is None: raise ValueError(...)` guard before predicate construction. | `translator/filters.py:41` |
| 12 | Wrap `_resolve_mark` in `layers.py` with context: `f"Entry {entry.measure!r} layer {i}: {e}"`. | `translator/patterns/layers.py:225` |
| 13 | `HTTPServer` cleanup via `with contextlib.closing(server):`. | `cli/dev.py:295` |
| 14 | Configure ruff: `lint.select = ["E","F","W","I","B","UP","C4","SIM","RUF"]`. | `pyproject.toml:72` |
| 15 | Add unit tests for the 10 untested modules — start with `theme/merge.py`, `translator/sort.py`, `translator/encodings.py`. | `tests/` |

### Tier 4 — Optional / OCP polish

| # | Action |
|---|---|
| 16 | Filter operator registry: `FILTER_OPERATOR_VALIDATORS: dict[FilterOperator, Callable]` replacing the `_validate_operator_and_values` switch. |
| 17 | Pattern compiler registry replacing the `isinstance(spec.rows, list)` router in `translate.py:54`. |
| 18 | Inject a `FieldTypeResolver` into `translate_chart` instead of constructing `ModelResolver(model)` internally (DIP). |
| 19 | Decompose `layout_solver._resolve_children` into `_classify_sizes`, `_resolve_underconstrained`, `_resolve_overconstrained_proportional`, `_resolve_overconstrained_full`. |

---

## Bottom Line

The compilation core (parse → translate → theme → render) is **clean, well-documented, and Pydantic-validated** — the project's strongest asset. The weakness lives entirely at the **edges**: the studio web layer and the Cube integration are where SOLID erodes, where exceptions get swallowed, and where the same logic appears multiple times.

**Tier 1** items (extract `pipeline.py`, split `studio/server.py`, share pattern logic) eliminate the bulk of the duplication and make every later refactor cheaper. **Tier 3 item 8** (XSS escape) is small but worth doing immediately given Phase 6's web-app trajectory.
