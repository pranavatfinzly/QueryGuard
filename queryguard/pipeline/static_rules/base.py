"""Stage 3 — the rule protocol and registry.

Deterministic checks over parsed query ASTs. These run before any database is
provisioned, so their findings survive a provisioning failure.

Individual rules live one-per-file under :mod:`queryguard.pipeline.static_rules.rules`
and are named after the smell they detect (``SelectStarRule``,
``LeadingWildcardLikeRule``). Each ships with fixtures: one query it must flag,
and one similar query it must not.

Rules receive a :class:`RuleContext` — a parsed sqlglot AST plus provenance and
schema — never a raw string. Parsing happens once in the engine so that a rule
cannot re-parse with a different dialect, and so an unparseable query is recorded
as unanalyzable in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlglot import exp

from queryguard.models.finding import Finding, Severity, Suggestion
from queryguard.models.query import ExtractedQuery
from queryguard.pipeline.static_rules.schema import (
    UNKNOWN_SCHEMA,
    SchemaProvider,
)

__all__ = [
    "RULES",
    "Rule",
    "RuleContext",
    "clause",
    "has_clause",
    "register",
    "run_static_rules",
]


def has_clause(node: exp.Expression, *keys: str) -> bool:
    """Whether a statement carries any of these clauses.

    Presence is tested by truthiness, not ``is not None``, because sqlglot marks an
    absent clause inconsistently: ``None`` in most slots but ``False`` in others —
    ``Delete.args["using"]`` is ``False`` for a plain ``DELETE``. An ``is not None``
    check reads as correct and silently treats every bare DELETE as scoped.

    Truthiness is safe here: ``exp.Expression`` defines neither ``__bool__`` nor
    ``__len__``, so a real clause node is always truthy.
    """
    return any(bool(node.args.get(key)) for key in keys)


def clause(node: exp.Expression, *keys: str) -> exp.Expression | None:
    """The first of these clauses present on a statement, as a node.

    Accepts several keys because sqlglot renames arg keys across versions — a
    ``SELECT``'s FROM clause is ``from_`` in 30.x and ``from`` before it.
    """
    for key in keys:
        value = node.args.get(key)
        if isinstance(value, exp.Expression):
            return value
    return None


@dataclass(frozen=True)
class RuleContext:
    """Everything a rule may look at.

    Not a Pydantic model: it carries a live sqlglot ``Expression``, which is a
    mutable tree with no serialization contract. Stage *outputs* are Pydantic
    models (:class:`Finding`); this is an intra-stage argument holder.
    """

    query: ExtractedQuery
    ast: exp.Expression
    schema: SchemaProvider = UNKNOWN_SCHEMA

    def finding(
        self,
        *,
        rule_id: str,
        severity: Severity,
        title: str,
        explanation: str,
        impact: str,
        suggestions: list[Suggestion] | None = None,
    ) -> Finding:
        """Build a Finding already anchored to this query's provenance."""
        return Finding(
            rule_id=rule_id,
            severity=severity,
            title=title,
            explanation=explanation,
            impact=impact,
            provenance=self.query.provenance,
            query_id=self.query.id,
            suggestions=suggestions or [],
        )


class Rule(Protocol):
    """A single static check over one parsed query."""

    rule_id: str

    def check(self, context: RuleContext) -> list[Finding]:
        """Return findings for this query, or an empty list if it is clean."""
        ...


RULES: list[Rule] = []


def register(rule: Rule) -> Rule:
    """Register a rule instance in the global registry.

    Takes an instance, not a class: the :class:`Rule` protocol requires a bound
    ``check``, and a class object would satisfy the attribute check while failing
    at call time.
    """
    RULES.append(rule)
    return rule


def run_static_rules(
    queries: list[ExtractedQuery],
    schema: SchemaProvider = UNKNOWN_SCHEMA,
) -> list[Finding]:
    """Run every registered rule over every parseable query.

    Thin wrapper over :class:`~queryguard.pipeline.static_rules.engine.RuleEngine`,
    kept because it is the stage entry point the pipeline and the API wiring name.
    """
    # Imported here: engine imports this module for RuleContext, so a module-level
    # import would be circular.
    from queryguard.pipeline.static_rules.engine import RuleEngine

    return RuleEngine(schema=schema).analyze(queries)
