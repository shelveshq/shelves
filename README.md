# Charter

AI-native declarative visual analytics platform. Translates a Tableau-inspired
YAML DSL into Vega-Lite JSON specs.

## Quick Start

```bash
pip install -e ".[dev]"
pytest
python -m src.cli.render tests/fixtures/yaml/simple_bar.yaml --data tests/fixtures/data/orders.json
```

## Pipeline

```
YAML chart spec -> parse (Pydantic) -> translate -> merge theme -> bind data -> render HTML
```

See PLAN.md for the full implementation roadmap.
See docs/ for the DSL specification, architecture, and vision documents.
