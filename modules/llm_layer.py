"""Stage 7 — N+1 detection, and explanation rendering.

Uses the Claude API (``claude-opus-5``) via the ``anthropic`` SDK to reason
*across* the whole diff's query set — a query inside a loop, a lazy association
dereferenced per row, a derived method called per element of a collection — which
no single-query rule can see.

Conventions from CLAUDE.md:

- Structured outputs (``output_config.format``) so findings deserialize straight
  into :class:`~modules.models.Finding`.
- Keep the system prompt and rule descriptions stable and cached; put the
  per-PR diff and query set after the cache breakpoint.
- Check ``stop_reason == "refusal"`` before reading ``response.content``.
- Findings are claims, not facts. Verify what is checkable against a plan or the
  AST; label ``confidence`` on what is not.
"""

from __future__ import annotations

from modules.models import ExtractedQuery, Finding

__all__ = ["MODEL", "detect_n_plus_one", "explain_finding"]

MODEL = "claude-opus-5"


def detect_n_plus_one(
    queries: list[ExtractedQuery],
    diff: str,
    statement_log: list[str] | None = None,
) -> list[Finding]:
    """Identify N+1 access patterns across the diff.

    ``statement_log`` carries p6spy-captured statements from the test suite when
    available, which makes repeated-execution patterns directly observable.
    """
    raise NotImplementedError("llm_layer.detect_n_plus_one is not implemented yet")


def explain_finding(finding: Finding) -> str:
    """Render a developer-facing explanation of why a finding matters."""
    raise NotImplementedError("llm_layer.explain_finding is not implemented yet")
