"""Stage 3 — Static analysis.

Deterministic rule checks over parsed query ASTs. Runs before any database is
provisioned, so these findings survive a provisioning failure.

Planned rules: ``SELECT *``, missing ``WHERE``, leading-wildcard ``LIKE``,
functions wrapping indexed columns, implicit casts, unbounded result sets,
``OFFSET``-based deep paging, ``IN`` lists that should be joins, cartesian
products, and derived-method patterns that fan out.

Each rule ships with fixtures: one query it must flag, and one similar query it
must not.
"""

from __future__ import annotations

from typing import Protocol

from modules.models import ExtractedQuery, Finding

__all__ = ["Rule", "RULES", "register", "run_static_rules"]


class Rule(Protocol):
    """A single static check over one extracted query."""

    rule_id: str

    def check(self, query: ExtractedQuery) -> list[Finding]:
        """Return findings for this query, or an empty list if it is clean."""
        ...


RULES: list[Rule] = []


def register(rule: Rule) -> Rule:
    """Register a rule in the global registry. Intended as a decorator."""
    RULES.append(rule)
    return rule


def run_static_rules(queries: list[ExtractedQuery]) -> list[Finding]:
    """Run every registered rule over every parseable query."""
    raise NotImplementedError("static_rules.run_static_rules is not implemented yet")
