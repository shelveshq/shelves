"""
Parameter Substitution

Replaces `$name` / `${name}` references in a raw YAML dict with resolved
parameter values, BEFORE Pydantic parsing. What comes out is an ordinary chart
spec — nothing parameter-shaped survives, so no downstream layer needs to know
parameters exist.

**The walk never raises for a reference problem.** Undeclared references,
forbidden positions, and type mismatches are collected as diagnostics and the
caller decides what to do. That is what lets a future template-expansion pass
run ahead of this one and consume its own refs first.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from shelves.params.positions import classify
from shelves.params.refs import (
    INTERP_RE,
    interp_refs,
    unescape_dollars,
    whole_ref,
)
from shelves.params.schema import ParametersBlock, validate_value

if TYPE_CHECKING:
    from shelves.data.domains import Domain

DiagnosticCode = Literal["undeclared_ref", "forbidden_position", "type_mismatch"]

_FILTER_INDEX_RE = re.compile(r"^filters\[(\d+)\]")

_INLINE_BLOCK_ERROR = (
    "'parameters' is not a chart or dashboard property — parameters are "
    "declared once for the project in models/parameters.yaml and referenced "
    "here with $name."
)

_FORBIDDEN_MESSAGE = (
    "parameter references are not allowed here. Parameters may appear in "
    "field slots, filter values, and title text only — never in mark types, "
    "style values, or layout structure."
)


@dataclass(frozen=True)
class Diagnostic:
    code: DiagnosticCode
    message: str
    path: str
    name: str
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True)
class SubstitutionResult:
    data: dict[str, Any]
    diagnostics: list[Diagnostic]

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]


class ParameterSet:
    """Declarations plus the resolved value for each — what a compile needs.

    Built once per render and threaded to every chart, so all sheets in a
    dashboard see identical values.
    """

    def __init__(
        self,
        declared: ParametersBlock,
        overrides: dict[str, Any] | None = None,
        domains: dict[str, Domain] | None = None,
    ) -> None:
        """
        `domains` comes from `shelves.data.domains.resolve_parameter_domains`.
        None means "not resolved" — every call site that predates SHE-90 keeps
        working, and an override against a field-reference domain goes
        unchecked exactly as it did before.
        """
        # Imported here, not at module level: shelves/data/ imports from
        # shelves/params/, so a top-level import would close the cycle.
        from shelves.data.domains import check_value_in_domain

        self.declared = declared
        self.domains = domains or {}
        values: dict[str, Any] = {name: p.default for name, p in declared.items()}

        for key, value in (overrides or {}).items():
            if key not in declared:
                raise ValueError(
                    f"{key!r} is not a declared parameter. Declared in "
                    f"parameters.yaml: {', '.join(sorted(declared)) or '(none)'}."
                )
            try:
                validate_value(declared[key], value)
            except ValueError as e:
                raise ValueError(f"parameters.{key}: {e}") from e
            # check_value_in_domain already prefixes "parameters.<key>: ".
            # label="value": this is an override, not a declaration's default.
            if key in self.domains:
                check_value_in_domain(key, value, self.domains[key], label="value")
            values[key] = value

        self.values = values

    @classmethod
    def empty(cls) -> ParameterSet:
        """A set with no declarations — the no-parameters-file case."""
        return cls({})


def substitute_parameters(
    raw: dict[str, Any],
    parameters: ParameterSet,
) -> SubstitutionResult:
    """Replace `$refs` in a raw YAML dict with resolved parameter values."""
    if isinstance(raw, dict) and "parameters" in raw:
        raise ValueError(_INLINE_BLOCK_ERROR)

    if not parameters.declared and not _contains_dollar(raw):
        # Nothing to do — hand the caller its own dict back, uncopied.
        return SubstitutionResult(raw, [])

    walker = _Walker(parameters)
    data = walker.walk(copy.deepcopy(raw), "")
    _prune_null_filters(data, walker.null_filter_indices)
    return SubstitutionResult(data, walker.diagnostics)


class _Walker:
    def __init__(self, parameters: ParameterSet) -> None:
        self._params = parameters
        self.diagnostics: list[Diagnostic] = []
        self.null_filter_indices: set[int] = set()

    # ─── traversal ────────────────────────────────────────────

    def walk(self, node: Any, path: str) -> Any:
        if isinstance(node, dict):
            return {k: self.walk(v, _join(path, k)) for k, v in node.items()}
        if isinstance(node, list):
            return [self.walk(v, f"{path}[{i}]") for i, v in enumerate(node)]
        return self._scalar(node, path)

    def _scalar(self, value: Any, path: str) -> Any:
        name = whole_ref(value)
        if name is not None:
            return self._resolve_whole(name, path, value)

        if isinstance(value, str):
            if INTERP_RE.search(value):
                value = self._resolve_interpolation(value, path)
            if isinstance(value, str):
                value = unescape_dollars(value)
        return value

    # ─── resolution ───────────────────────────────────────────

    def _resolve_whole(self, name: str, path: str, original: str) -> Any:
        kind = classify(path)

        if kind is None:
            self._error("forbidden_position", _FORBIDDEN_MESSAGE, path, name)
            return original

        if kind == "interpolation":
            self._error(
                "forbidden_position",
                f"a bare $ref cannot fill this position. Use ${{{name}}} to "
                "interpolate the value into the text.",
                path,
                name,
            )
            return original

        declared = self._params.declared.get(name)
        if declared is None:
            self._undeclared(name, path)
            return original

        if kind == "field" and declared.type != "field":
            self._error(
                "type_mismatch",
                f"${name} ({declared.type}) cannot fill a field slot. Field "
                "slots accept only type 'field' parameters.",
                path,
                name,
            )
            return original

        if kind == "literal" and declared.type == "field":
            self._error(
                "type_mismatch",
                f"${name} (field) cannot fill a filter value. Filter values "
                "accept string, number, and date parameters.",
                path,
                name,
            )
            return original

        resolved = self._params.values[name]
        if kind == "literal" and resolved is None:
            index = _filter_index(path)
            if index is not None:
                self.null_filter_indices.add(index)
        return resolved

    def _resolve_interpolation(self, text: str, path: str) -> str:
        if classify(path) != "interpolation":
            names = interp_refs(text)
            self._error("forbidden_position", _FORBIDDEN_MESSAGE, path, names[0] if names else "")
            return text

        missing = [n for n in interp_refs(text) if n not in self._params.declared]
        for name in missing:
            self._undeclared(name, path)
        if missing:
            return text

        def render(match: re.Match[str]) -> str:
            value = self._params.values[match.group(1)]
            return "" if value is None else str(value)

        return INTERP_RE.sub(render, text)

    # ─── diagnostics ──────────────────────────────────────────

    def _error(self, code: DiagnosticCode, message: str, path: str, name: str) -> None:
        self.diagnostics.append(
            Diagnostic(code=code, message=f"{path}: {message}", path=path, name=name)
        )

    def _undeclared(self, name: str, path: str) -> None:
        declared = ", ".join(sorted(self._params.declared)) or "(none)"
        self._error(
            "undeclared_ref",
            f"${name} is not a declared parameter. Declared in models/parameters.yaml: {declared}.",
            path,
            name,
        )


def substitute_calculation(
    calc: str,
    parameters: ParameterSet,
    *,
    context: str,
) -> str:
    """Replace `$name` parameter references in a SQL calculation string.

    Unlike the chart-YAML walk, this raises immediately on problems —
    a bad reference in SQL is a hard error, not a collected diagnostic.
    """
    if "${" not in calc:
        return calc

    declared = parameters.declared

    for m in INTERP_RE.finditer(calc):
        if m.start() > 0 and calc[m.start() - 1] == "$":
            continue
        name = m.group(1)
        if name not in declared:
            declared_names = ", ".join(sorted(declared)) or "(none)"
            raise ValueError(
                f'"${{{name}}}" in calculation of {context} is not a declared '
                f"parameter. Declared: {declared_names}."
            )
        value = parameters.values[name]
        if value is None:
            raise ValueError(
                f"Parameter '{name}' resolves to null, which cannot be "
                f"substituted into a SQL calculation."
            )

    def _replace(match: re.Match[str]) -> str:
        if match.start() > 0 and calc[match.start() - 1] == "$":
            return match.group(0)
        return str(parameters.values[match.group(1)])

    result = INTERP_RE.sub(_replace, calc)
    return unescape_dollars(result)


# ─── helpers ──────────────────────────────────────────────────


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _filter_index(path: str) -> int | None:
    match = _FILTER_INDEX_RE.match(path)
    return int(match.group(1)) if match else None


def _contains_dollar(node: Any) -> bool:
    """Cheap pre-check so a spec with no references is never copied."""
    if isinstance(node, str):
        return "$" in node
    if isinstance(node, dict):
        return any(_contains_dollar(v) for v in node.values())
    if isinstance(node, list):
        return any(_contains_dollar(v) for v in node)
    return False


def _prune_null_filters(data: Any, indices: set[int]) -> None:
    """Drop filters whose value resolved to null — null means unfiltered.

    Required, not cosmetic: ShelfFilter's validator raises when an operator's
    required value key is None, so a null must never reach Pydantic.
    """
    if not indices or not isinstance(data, dict):
        return
    filters = data.get("filters")
    if not isinstance(filters, list):
        return
    data["filters"] = [f for i, f in enumerate(filters) if i not in indices]
