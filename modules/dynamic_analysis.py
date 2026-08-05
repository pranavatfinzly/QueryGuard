"""Stages 4–6 — Provision, plan analysis, and index simulation.

Everything in this module runs against an **isolated reference database** cloned
per PR run. Two invariants, from CLAUDE.md:

1. Never connect to a developer or production database.
2. Every executed statement is wrapped in ``BEGIN`` … ``ROLLBACK`` — nothing
   commits, including HypoPG index creation.

Note that hypothetical indexes are visible to ``EXPLAIN`` but **not** to
``EXPLAIN ANALYZE``, so the after-cost measurement uses plain ``EXPLAIN``. Call
``hypopg_reset()`` between candidates so simulations do not compound.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from modules.models import ExtractedQuery, Finding, Suggestion

__all__ = [
    "provision_reference_db",
    "rollback_transaction",
    "explain_analyze",
    "analyze_plan",
    "simulate_indexes",
]


@contextmanager
def provision_reference_db(snapshot: str) -> Iterator[Any]:
    """Start an isolated Postgres 16 + HypoPG container from a schema snapshot.

    Creates the ``hypopg`` extension, yields a connection, and tears the
    container down on exit. One database per run; never reused across runs.
    """
    raise NotImplementedError(
        "dynamic_analysis.provision_reference_db is not implemented yet"
    )


@contextmanager
def rollback_transaction(connection: Any) -> Iterator[Any]:
    """Yield a cursor inside ``BEGIN`` and always ``ROLLBACK`` on exit.

    Every statement executed against the reference DB goes through this helper.
    Pipeline modules must not open raw cursors.
    """
    raise NotImplementedError(
        "dynamic_analysis.rollback_transaction is not implemented yet"
    )


def explain_analyze(connection: Any, query: ExtractedQuery) -> dict[str, Any]:
    """Run ``EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`` inside a rolled-back tx.

    Placeholder parameters are bound before execution. Returns the parsed plan
    JSON.
    """
    raise NotImplementedError("dynamic_analysis.explain_analyze is not implemented yet")


def analyze_plan(query: ExtractedQuery, plan: dict[str, Any]) -> list[Finding]:
    """Inspect a plan tree for performance problems.

    Looks for sequential scans on large tables, bad row estimates,
    nested-loop blowups, external sorts, and spilled hashes.
    """
    raise NotImplementedError("dynamic_analysis.analyze_plan is not implemented yet")


def simulate_indexes(
    connection: Any,
    query: ExtractedQuery,
    plan: dict[str, Any],
) -> list[Suggestion]:
    """Propose candidate indexes and measure their simulated impact via HypoPG.

    For each candidate: ``hypopg_create_index`` → plain ``EXPLAIN`` → record the
    before/after cost delta → ``hypopg_reset``. Only candidates clearing the
    configured improvement threshold are returned.
    """
    raise NotImplementedError("dynamic_analysis.simulate_indexes is not implemented yet")
