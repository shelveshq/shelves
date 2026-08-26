"""
Grammar card loader (SHE-57).

The grammar card is the whole DSL on one page, hand-written for context
injection and served as MCP resource `shelves://grammar` (see `server.py`). This
module is the single read site — `server.py` and the tests both call
`grammar_card()` — and it owns the token budget the card is gated against.

Dependency-free on purpose: the token estimate is the spec-sanctioned
~4-chars/token approximation (`LLM Writability Specification.md` §3.1), not a
model tokenizer, so it is deterministic and needs no extra package.
"""

from __future__ import annotations

from importlib.resources import files

# Hard budget from LLM Writability Spec §3.1. The card must fit comfortably in an
# agent's working context alongside the model menu and the task.
GRAMMAR_TOKEN_BUDGET = 2500


def grammar_card() -> str:
    """The grammar-card markdown, read from package data (wheel-safe)."""
    return (files("shelves.mcp") / "resources" / "grammar.md").read_text(encoding="utf-8")


def estimate_tokens(text: str) -> int:
    """Conservative ~4-chars/token estimate (ceil). Over-counts real BPE tokens
    for English + YAML, so passing this budget is a genuine pass."""
    return -(-len(text) // 4)
