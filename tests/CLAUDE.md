# Tests — CLAUDE.md

## Running Tests

```bash
# All tests
.venv/bin/pytest

# Single test
.venv/bin/pytest tests/test_translator.py::TestSingleMarkCharts::test_simple_bar
```

## Conventions

- Test files map 1:1 to features — `test_<feature>.py` (e.g. `test_schema.py`, `test_translator.py`, `test_stacked.py`, `test_layers.py`, `test_layout_schema.py`, `test_layout_solver.py`, `test_duckdb_adapter.py`, `test_cube_client.py`, `test_dashboard_compose.py`, `test_pipeline.py`, `test_studio_*.py`). Add a new file when you add a feature rather than overloading an existing one.
- YAML fixtures live in `tests/fixtures/yaml/`, JSON data in `tests/fixtures/data/`
- `conftest.py` provides `load_yaml(name)` and `load_data(name)` helpers
- Pure browser-side JS sizing math is tested under node's built-in runner: `node --test shelves/render/*.test.js` (zero npm deps). DOM/label placement is verified manually — see `shelves/render/CLAUDE.md`.

## Mocking

- Cube tests use `respx` to mock HTTP — no live Cube instance needed for CI
- Do not mock internal modules when integration tests are feasible
