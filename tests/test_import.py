"""
Tests for CSV import & auto-model generation (KAN-216).

Tests cover schema inference (DuckDB type mapping, slugification, label generation),
model YAML generation (_row_count, special columns), and the CLI entry point.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from shelves.data.model_generator import generate_model_yaml
from shelves.data.schema_inference import InferredField, infer_schema
from shelves.models.schema import DataModel

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DATA_DIR = FIXTURES_DIR / "data"


# ─── Schema Inference ────────────────────────────────────────────────


class TestInferSchema:
    def test_basic_csv(self):
        schema = infer_schema(DATA_DIR / "import_sales.csv")
        assert schema == {
            "region": {"type": "nominal", "label": "Region"},
            "product": {"type": "nominal", "label": "Product"},
            "order_date": {"type": "temporal", "label": "Order Date", "defaultGrain": "day"},
            "revenue": {"type": "measure", "label": "Revenue", "aggregation": "sum"},
            "quantity": {"type": "measure", "label": "Quantity", "aggregation": "sum"},
            "is_returned": {"type": "nominal", "label": "Is Returned"},
        }

    def test_special_column_names(self):
        schema = infer_schema(DATA_DIR / "import_special_cols.csv")
        assert schema == {
            "sales_region": {
                "type": "nominal",
                "label": "Sales Region",
                "column": "Sales Region",
            },
            "order_date": {
                "type": "temporal",
                "label": "Order Date",
                "column": "Order Date",
                "defaultGrain": "day",
            },
            "revenue": {
                "type": "measure",
                "label": "Revenue ($)",
                "column": "Revenue ($)",
                "aggregation": "sum",
            },
            "qty_ordered": {
                "type": "measure",
                "label": "Qty Ordered",
                "column": "Qty Ordered",
                "aggregation": "sum",
            },
        }

    def test_integer_columns(self, tmp_path):
        csv_file = tmp_path / "ints.csv"
        csv_file.write_text("id,name,count\n1,Widget,100\n2,Gadget,200\n")
        schema = infer_schema(csv_file)
        assert schema["id"]["type"] == "measure"
        assert schema["id"]["aggregation"] == "sum"
        assert schema["name"]["type"] == "nominal"
        assert schema["count"]["type"] == "measure"
        assert schema["count"]["aggregation"] == "sum"


# ─── Model YAML Generation ──────────────────────────────────────────


class TestGenerateModel:
    def test_basic_csv(self):
        schema: dict[str, InferredField] = {
            "region": {"type": "nominal", "label": "Region"},
            "product": {"type": "nominal", "label": "Product"},
            "order_date": {"type": "temporal", "label": "Order Date", "defaultGrain": "day"},
            "revenue": {"type": "measure", "label": "Revenue", "aggregation": "sum"},
            "quantity": {"type": "measure", "label": "Quantity", "aggregation": "sum"},
            "is_returned": {"type": "nominal", "label": "Is Returned"},
        }
        yaml_str = generate_model_yaml(schema, "sales", "sales.csv")
        parsed = yaml.safe_load(yaml_str)

        assert parsed["model"] == "sales"
        assert parsed["label"] == "Sales"
        assert parsed["source"] == {"type": "file", "path": "sales.csv"}

        dims = parsed["dimensions"]
        assert list(dims.keys()) == ["region", "product", "order_date", "is_returned"]
        assert dims["region"] == {"column": "region", "label": "Region"}
        assert dims["order_date"] == {
            "column": "order_date",
            "type": "temporal",
            "label": "Order Date",
            "defaultGrain": "day",
        }

        measures = parsed["measures"]
        assert list(measures.keys()) == ["revenue", "quantity", "_row_count"]
        assert measures["revenue"] == {
            "column": "revenue",
            "aggregation": "sum",
            "label": "Revenue",
        }
        assert measures["_row_count"] == {
            "column": "region",
            "aggregation": "count",
            "label": "Row Count",
        }

    def test_special_column_names(self):
        schema: dict[str, InferredField] = {
            "sales_region": {
                "type": "nominal",
                "label": "Sales Region",
                "column": "Sales Region",
            },
            "order_date": {
                "type": "temporal",
                "label": "Order Date",
                "column": "Order Date",
                "defaultGrain": "day",
            },
            "revenue": {
                "type": "measure",
                "label": "Revenue ($)",
                "column": "Revenue ($)",
                "aggregation": "sum",
            },
            "qty_ordered": {
                "type": "measure",
                "label": "Qty Ordered",
                "column": "Qty Ordered",
                "aggregation": "sum",
            },
        }
        yaml_str = generate_model_yaml(schema, "special", "special.csv")
        parsed = yaml.safe_load(yaml_str)

        dims = parsed["dimensions"]
        assert dims["sales_region"]["column"] == "Sales Region"
        assert dims["order_date"]["column"] == "Order Date"

        measures = parsed["measures"]
        assert measures["revenue"]["column"] == "Revenue ($)"
        assert measures["qty_ordered"]["column"] == "Qty Ordered"

    def test_row_count_always_present(self):
        schema: dict[str, InferredField] = {
            "region": {"type": "nominal", "label": "Region"},
            "revenue": {"type": "measure", "label": "Revenue", "aggregation": "sum"},
        }
        yaml_str = generate_model_yaml(schema, "test", "test.csv")
        parsed = yaml.safe_load(yaml_str)

        measures = parsed["measures"]
        assert list(measures.keys()) == ["revenue", "_row_count"]
        assert measures["_row_count"] == {
            "column": "region",
            "aggregation": "count",
            "label": "Row Count",
        }

    def test_all_string_columns(self):
        schema: dict[str, InferredField] = {
            "name": {"type": "nominal", "label": "Name"},
            "city": {"type": "nominal", "label": "City"},
        }
        yaml_str = generate_model_yaml(schema, "people", "people.csv")
        parsed = yaml.safe_load(yaml_str)

        assert parsed["model"] == "people"
        assert parsed["label"] == "People"
        assert parsed["source"] == {"type": "file", "path": "people.csv"}

        dims = parsed["dimensions"]
        assert list(dims.keys()) == ["name", "city"]

        measures = parsed["measures"]
        assert list(measures.keys()) == ["_row_count"]
        assert measures["_row_count"] == {
            "column": "name",
            "aggregation": "count",
            "label": "Row Count",
        }

        # Validate the generated model conforms to the DataModel schema
        DataModel.model_validate(parsed)


# ─── CLI Integration ─────────────────────────────────────────────────


class TestImportCLI:
    def _run_import(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "shelves.cli.import_cmd", *args],
            capture_output=True,
            text=True,
        )

    def test_creates_model_file(self, tmp_path):
        models_dir = tmp_path / "models"
        csv_path = DATA_DIR / "import_sales.csv"
        result = self._run_import(str(csv_path), "--models-dir", str(models_dir))

        assert result.returncode == 0, result.stderr
        model_path = models_dir / "import_sales.yaml"
        assert model_path.exists()

        parsed = yaml.safe_load(model_path.read_text())
        model = DataModel.model_validate(parsed)
        assert model.model == "import_sales"
        assert model.source is not None
        assert model.source.type == "file"
        assert "Created model:" in result.stdout

    def test_custom_model_name(self, tmp_path):
        models_dir = tmp_path / "models"
        csv_path = DATA_DIR / "import_sales.csv"
        result = self._run_import(
            str(csv_path), "--name", "orders", "--models-dir", str(models_dir)
        )

        assert result.returncode == 0, result.stderr
        model_path = models_dir / "orders.yaml"
        assert model_path.exists()

        parsed = yaml.safe_load(model_path.read_text())
        assert parsed["model"] == "orders"

    def test_creates_models_dir_if_missing(self, tmp_path):
        models_dir = tmp_path / "new_dir" / "models"
        csv_path = DATA_DIR / "import_sales.csv"
        result = self._run_import(str(csv_path), "--models-dir", str(models_dir))

        assert result.returncode == 0, result.stderr
        assert models_dir.exists()
        assert (models_dir / "import_sales.yaml").exists()

    def test_source_path_relative(self, tmp_path, monkeypatch):
        models_dir = tmp_path / "models"
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        csv_src = DATA_DIR / "import_sales.csv"
        csv_dst = data_dir / "sales.csv"
        csv_dst.write_text(csv_src.read_text())

        monkeypatch.chdir(tmp_path)
        result = self._run_import(str(csv_dst), "--models-dir", str(models_dir))

        assert result.returncode == 0, result.stderr
        parsed = yaml.safe_load((models_dir / "sales.yaml").read_text())
        source_path = parsed["source"]["path"]
        assert not os.path.isabs(source_path)
        assert "data/sales.csv" in source_path or "data\\sales.csv" in source_path


# ─── Error Cases ─────────────────────────────────────────────────────


class TestImportErrors:
    def _run_import(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "shelves.cli.import_cmd", *args],
            capture_output=True,
            text=True,
        )

    def test_file_not_found(self):
        result = self._run_import("nonexistent.csv")
        assert result.returncode == 1
        assert "File not found" in result.stderr

    def test_unsupported_extension(self, tmp_path):
        xlsx = tmp_path / "data.xlsx"
        xlsx.write_bytes(b"\x00\x01")
        result = self._run_import(str(xlsx))
        assert result.returncode == 1
        assert "Unsupported file format" in result.stderr

    def test_model_name_collision(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "import_sales.yaml").write_text("existing: true")

        csv_path = DATA_DIR / "import_sales.csv"
        result = self._run_import(str(csv_path), "--models-dir", str(models_dir))
        assert result.returncode == 1
        assert "already exists" in result.stderr
        assert "--overwrite" in result.stderr

    def test_model_overwrite(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "import_sales.yaml").write_text("existing: true")

        csv_path = DATA_DIR / "import_sales.csv"
        result = self._run_import(str(csv_path), "--models-dir", str(models_dir), "--overwrite")
        assert result.returncode == 0, result.stderr
        parsed = yaml.safe_load((models_dir / "import_sales.yaml").read_text())
        assert parsed["model"] == "import_sales"

    def test_invalid_csv(self, tmp_path):
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        result = self._run_import(str(bad_csv))
        assert result.returncode == 1
        assert "Failed to read" in result.stderr
