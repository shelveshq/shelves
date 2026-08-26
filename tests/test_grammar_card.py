"""
Grammar card tests (SHE-57).

The grammar card (`shelves/mcp/resources/grammar.md`) is the whole DSL on one
page, served as MCP resource `shelves://grammar`. These are the machine guards
that keep it honest independent of its wording: a hard token budget, a smoke
test that every YAML example on the card validates against the semantic model,
a resource round trip, and a mark-coverage reminder.

Contract: `LLM Writability Specification.md` §3.1.
"""

from __future__ import annotations

import re

import pytest
import yaml

from shelves.mcp.grammar import GRAMMAR_TOKEN_BUDGET, estimate_tokens, grammar_card
from shelves.pipeline import compile_chart
from shelves.schema.chart_schema import MarkType
from shelves.validation import detect_kind, validate_dashboard_yaml
from tests.conftest import FIXTURES_DIR, MODELS_DIR

_YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.DOTALL)


def _yaml_blocks(text: str) -> list[str]:
    """Every ```yaml fenced block on the card. Fragments that are not compilable
    specs (the inheritance sketch, the parameter example the MCP tools can't
    resolve) use a non-yaml fence (```text) and are deliberately excluded."""
    return [m.group(1) for m in _YAML_BLOCK.finditer(text)]


def _section(text: str, heading: str) -> str:
    """The body of a `## heading` section, up to the next `## ` heading."""
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## )", text, re.DOTALL | re.MULTILINE)
    assert m is not None, f"Section {heading!r} not found on the card."
    return m.group(1)


# ─── loading ──────────────────────────────────────────────────────


def test_grammar_card_loads():
    text = grammar_card()
    assert text.strip()
    assert text.lstrip().startswith("#")


# ─── token budget (the CI gate) ───────────────────────────────────


def test_estimate_tokens_is_ceil_div_four():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2  # ceil(5/4)
    assert estimate_tokens("a" * 10000) == 2500


def test_grammar_card_within_token_budget():
    tokens = estimate_tokens(grammar_card())
    assert tokens <= GRAMMAR_TOKEN_BUDGET, (
        f"Grammar card is {tokens} tokens, over the {GRAMMAR_TOKEN_BUDGET} budget. "
        "Cut content — the card is canonical forms only (LLM Writability Spec §3.1)."
    )


# ─── snippet smoke test ───────────────────────────────────────────


def test_card_has_yaml_snippets():
    # Guards the smoke test below against silently passing on an empty match set
    # (e.g. someone renames the fence language).
    assert len(_yaml_blocks(grammar_card())) >= 8


def test_every_yaml_snippet_compiles():
    # Compile (not just validate) so the card cannot ship a snippet that passes
    # schema/model checks but blows up in the translator — the gap a ```yaml
    # parameter example would fall into (it can't compile through the tools, so
    # it lives in a ```text fence and is excluded here).
    blocks = _yaml_blocks(grammar_card())
    for i, block in enumerate(blocks):
        raw = yaml.safe_load(block)
        if isinstance(raw, dict) and detect_kind(raw) == "dashboard":
            result = validate_dashboard_yaml(block, models_dir=MODELS_DIR, project_dir=FIXTURES_DIR)
            assert result.valid, (
                f"Grammar card dashboard snippet #{i} failed to validate:\n{block}\n"
                f"errors: {[e.model_dump() for e in result.errors]}"
            )
            continue
        try:
            compile_chart(block, models_dir=MODELS_DIR)
        except Exception as e:
            raise AssertionError(
                f"Grammar card yaml snippet #{i} failed to compile:\n{block}"
            ) from e


# ─── resource registration ────────────────────────────────────────


def test_grammar_resource_registered_and_served():
    import anyio
    from mcp.server.lowlevel.helper_types import ReadResourceContents

    from shelves.mcp.server import build_server
    from shelves.mcp.tools import MCPContext

    server = build_server(MCPContext.create(project_dir=FIXTURES_DIR, models_dir=MODELS_DIR))

    async def go():
        resources = await server.list_resources()
        by_uri = {str(r.uri): r for r in resources}
        assert "shelves://grammar" in by_uri
        assert by_uri["shelves://grammar"].mime_type == "text/markdown"

        contents = list(await server.read_resource("shelves://grammar"))
        assert contents
        first = contents[0]
        assert isinstance(first, ReadResourceContents)
        assert first.content == grammar_card()

    anyio.run(go)


# ─── coverage reminder ────────────────────────────────────────────


def test_grammar_card_lists_every_mark_in_closed_set():
    # Scope to the "Marks (closed set)" section, not the whole card — otherwise
    # marks like `line`/`bar`/`text` pass on incidental prose rather than on the
    # closed-set list this guard is meant to keep complete.
    marks_section = _section(grammar_card(), "Marks (closed set)")
    for mark in MarkType.__args__:  # type: ignore[attr-defined]
        assert f"`{mark}`" in marks_section, (
            f"Mark {mark!r} is missing from the Marks (closed set) list."
        )


@pytest.mark.parametrize(
    "pattern_keyword",
    ["scatter", "heatmap", "facet", "layer", "kpi", "filters", "sort"],
)
def test_grammar_card_mentions_pattern(pattern_keyword: str):
    assert pattern_keyword in grammar_card().lower()
