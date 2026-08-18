"""
CLI: Lint chart / dashboard YAML specs (SHE-54)

Usage:
  shelves-lint chart.yaml
  shelves-lint charts/ --models-dir models/
  shelves-lint chart.yaml dashboard.yaml --models-dir models/

Validates specs without rendering. Reports every error at once with line
numbers, valid options, and "did you mean" suggestions, then exits non-zero on
any error (CI-friendly). This is the human-readable face of the same renderer
the MCP `validate_spec` tool consumes — one renderer, three surfaces.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml as yaml_lib

from shelves.validation import (
    ValidationErrorItem,
    ValidationResult,
    detect_kind,
    validate_chart_yaml,
    validate_dashboard_yaml,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate chart/dashboard specs and report structured errors."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Spec files or directories (directories are searched for *.yaml).",
    )
    parser.add_argument(
        "--models-dir",
        help="Directory containing model YAML files (enables semantic-model checks).",
    )
    return parser


def _collect_files(paths: list[str]) -> list[Path]:
    """Expand each path: files as-is, directories globbed for *.yaml/*.yml."""
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(q for q in p.rglob("*.yaml")))
            files.extend(sorted(q for q in p.rglob("*.yml")))
        else:
            files.append(p)
    return files


def _is_model_manifest(raw: object) -> bool:
    """True if the parsed YAML looks like a model manifest (has `model` + `measures`)."""
    return isinstance(raw, dict) and "model" in raw and "measures" in raw


def _format_error(file: Path, err: ValidationErrorItem) -> str:
    """`path:line:col  [code]  message (did you mean 'x'?)` for one error."""
    line = err.line if err.line is not None else "?"
    col = err.col if err.col is not None else "?"
    loc = f"{file}:{line}:{col}"
    suffix = f" (did you mean '{err.did_you_mean}'?)" if err.did_you_mean else ""
    return f"{loc}  [{err.code}]  {err.message}{suffix}"


def _validate_file(path: Path, models_dir: str | None) -> ValidationResult | None:
    """Validate one file, or return None when it is a model manifest (skipped)."""
    text = path.read_text()
    # Parse once here; validate_* re-parses internally, but the manifest check
    # and kind detection share this single load rather than each re-parsing.
    try:
        raw = yaml_lib.safe_load(text)
    except yaml_lib.YAMLError:
        raw = None

    if _is_model_manifest(raw):
        return None

    kind = detect_kind(raw) if isinstance(raw, dict) else None
    if kind == "dashboard":
        return validate_dashboard_yaml(text, models_dir=models_dir, project_dir=path.parent)
    return validate_chart_yaml(text, models_dir=models_dir)


def main() -> None:
    args = build_parser().parse_args()

    files = _collect_files(args.paths)
    total_errors = 0
    checked = 0

    for path in files:
        if not path.exists():
            print(f"{path}: not found", file=sys.stderr)
            total_errors += 1
            continue

        result = _validate_file(path, args.models_dir)
        if result is None:
            print(f"{path}: skipped (model manifest)")
            continue

        checked += 1
        if result.valid:
            print(f"{path}: OK")
        else:
            for err in result.errors:
                print(_format_error(path, err))
            total_errors += len(result.errors)

    summary = f"Checked {checked} file(s); {total_errors} error(s)."
    print(summary)
    sys.exit(1 if total_errors else 0)


if __name__ == "__main__":
    main()
