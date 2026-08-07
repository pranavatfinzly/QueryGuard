"""Stage 7 — N+1 detection.

Reasons *across* the diff's query set rather than within one query: a query inside
a loop, a lazy association dereferenced per row, a derived method called per
element of a collection. No single-query rule can see any of these.

Where a p6spy statement log is available it is far stronger evidence than the
source alone — the same statement repeated once per row, with only the bind value
changing, is the signature of an N+1 and is directly countable. See
:mod:`queryguard.integrations.p6spy`.

The Claude call itself lives in :mod:`queryguard.integrations.claude`. Findings
from the model are claims, not facts: verify what is checkable against a plan or
the AST, and label ``confidence`` on what is not.
"""

from __future__ import annotations

from queryguard.integrations.p6spy import StatementGroup
from queryguard.models.finding import Finding
from queryguard.models.query import ExtractedQuery

__all__ = ["detect_n_plus_one"]


def detect_n_plus_one(
    queries: list[ExtractedQuery],
    diff: str,
    repeated_statements: list[StatementGroup] | None = None,
) -> list[Finding]:
    """Identify N+1 access patterns across the diff.

    ``repeated_statements`` carries the corroborating evidence from a p6spy log
    when a run captured one, as produced by
    :func:`queryguard.integrations.p6spy.find_repeated_statements`.
    """
    raise NotImplementedError("nplusone.detect_n_plus_one is not implemented yet")
