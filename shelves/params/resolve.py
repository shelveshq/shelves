"""
The single entry point every surface uses to obtain a ParameterSet.

Surfaces MUST call `load_parameter_set` rather than composing
`load_parameters` + `ParameterSet` themselves. That is what makes the render
CLI, the dev CLI, and both Studio compile paths behave identically — parity by
construction rather than by four call sites that happen to agree.

It is also the ONE call site for SHE-90's `resolve_parameter_domains`: a
field-reference `values:` entry becomes a real Domain HERE, between loading and
constructing, so nothing downstream changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from shelves.data.domains import resolve_parameter_domains
from shelves.params.coerce import coerce_overrides
from shelves.params.loader import load_parameters
from shelves.params.substitute import ParameterSet


def load_parameter_set(
    parameters_path: Path | str | None = None,
    *,
    models_dir: Path | str | None = None,
    data_base_dir: Path | None = None,
    overrides: Mapping[str, str] | None = None,
    resolve_domains: bool = True,
) -> ParameterSet:
    """Load declarations, resolve domains, coerce string overrides, build the set.

    Args:
        parameters_path: Explicit parameters.yaml path (the --parameters-file
            flag). None → `<models_dir>/parameters.yaml`.
        models_dir: Locates the default file, resolves `type: field` entries
            against their manifests, and locates models during domain
            resolution.
        data_base_dir: Base directory for relative inline/file source paths
            during domain resolution. MUST be the same value the calling
            surface passes to `resolve_model_data` / `compile_dashboard_charts`
            — otherwise a value is validated against one dataset and charted
            from another.
        overrides: Raw string values keyed by parameter name (--param).
        resolve_domains: When False, skip SHE-90 domain resolution entirely and
            build the set with no domains. Only the render CLI's `--no-data`
            sets this — it is NOT a per-surface preference.

    Returns:
        ParameterSet. A missing parameters file yields an EMPTY set, never an
        error — the backward-compatibility guarantee for every project that
        predates parameters.

    Raises:
        ValueError: the parameters file is present but invalid; a `type: field`
            parameter names a model or field that does not exist; an override
            cannot be coerced to its declared type; an override names an
            undeclared parameter or a value outside `values:`.
        ParameterDomainError (a ValueError): a field-reference domain cannot be
            resolved, or a default/override falls outside a resolved domain.
    """
    declared = load_parameters(parameters_path, models_dir=models_dir, validate_fields=True)

    # `and declared` keeps the guarantee that a project without parameters
    # performs no data access whatsoever structural rather than incidental.
    domains = (
        resolve_parameter_domains(declared, models_dir=models_dir, data_base_dir=data_base_dir)
        if resolve_domains and declared
        else {}
    )

    typed = coerce_overrides(declared, overrides or {})
    return ParameterSet(declared, typed, domains)
