"""Stage 3 — the rule protocol and registry.

Deterministic checks over parsed query ASTs. These run before any database is
provisioned, so their findings survive a provisioning failure.

Individual rules live one-per-file under :mod:`queryguard.pipeline.static_rules.rules`
and are named after the smell they detect (``SelectStarRule``,
``LeadingWildcardLikeRule``). Each ships with fixtures: one query it must flag,
and one similar query it must not.
"""

from __future__ import annotations

from typing import Protocol

from queryguard.models.finding import Finding
from queryguard.models.query import ExtractedQuery

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
