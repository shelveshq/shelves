# Tests — CLAUDE.md

## Running Tests

```bash
# All tests
.venv/bin/pytest

# Single test
.venv/bin/pytest tests/test_translator.py::TestSingleMarkCharts::test_simple_bar
```

## Conventions

- Test files map 1:1 to features: `test_schema.py`, `test_translator.py`, `test_stacked.py`, `test_facet.py`, `test_layers.py`, `test_render.py`, `test_cube_client.py`, `test_data_integration.py`, `test_model_resolver.py`, `test_model_schema.py`, `test_model_translate.py`, `test_dot_notation.py`
- YAML fixtures live in `tests/fixtures/yaml/`, JSON data in `tests/fixtures/data/`
- `conftest.py` provides `load_yaml(name)` and `load_data(name)` helpers

## Mocking

- Cube tests use `respx` to mock HTTP — no live Cube instance needed for CI
- Do not mock internal modules when integration tests are feasible
