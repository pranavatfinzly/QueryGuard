"""Deterministic merge-enforcement policy for QueryGuard findings.

This module is the sole authority for turning structured, deterministic
``Finding`` values into a pass/fail decision.  It deliberately has no dependency
on report rendering or LLM providers: prose is useful to a reviewer, but cannot
change whether a pull request is blocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Sequence
from typing import ClassVar

from queryguard.models.finding import Finding, Severity
from queryguard.models.report import Report

__all__ = [
    "DEFAULT_BLOCKING_SEVERITIES",
    "EnforcementPolicy",
    "EnforcementStatus",
    "InvalidEnforcementPolicy",
    "ReviewResult",
    "parse_rule_ids",
    "parse_severities",
]

DEFAULT_BLOCKING_SEVERITIES = frozenset({Severity.CRITICAL, Severity.HIGH})


class InvalidEnforcementPolicy(ValueError):
    """Raised when an enforcement setting cannot be interpreted safely."""


class EnforcementStatus(str, Enum):
    """The deterministic merge decision for one completed review."""

    PASS = "PASS"
    BLOCKED = "BLOCKED"


def parse_severities(value: str | None, *, setting_name: str) -> frozenset[Severity]:
    """Parse a comma-separated severity setting with clear validation errors.

    ``None`` means "use the caller's default" and is therefore not accepted here;
    callers choose their own default before parsing.  An empty or whitespace-only
    string deliberately means an empty set, which allows an operator to disable a
    particular policy dimension explicitly rather than relying on an ambiguous
    missing-variable behavior.
    """
    if value is None:
        msg = f"{setting_name} must be set before it can be parsed"
        raise InvalidEnforcementPolicy(msg)

    raw_names = [name.strip() for name in value.split(",")]
    if not any(raw_names):
        return frozenset()
    if any(not name for name in raw_names):
        msg = f"{setting_name} contains an empty severity name"
        raise InvalidEnforcementPolicy(msg)

    parsed: set[Severity] = set()
    for name in raw_names:
        try:
            parsed.add(Severity(name.lower()))
        except ValueError as error:
            choices = ", ".join(severity.name for severity in Severity)
            msg = f"{setting_name} has invalid severity {name!r}; expected one of: {choices}"
            raise InvalidEnforcementPolicy(msg) from error
    return frozenset(parsed)


def parse_rule_ids(value: str | None, *, setting_name: str) -> frozenset[str]:
    """Parse optional comma-separated rule IDs, rejecting accidental blanks."""
    if value is None or not value.strip():
        return frozenset()
    rule_ids = [rule_id.strip() for rule_id in value.split(",")]
    if any(not rule_id for rule_id in rule_ids):
        msg = f"{setting_name} contains an empty rule ID"
        raise InvalidEnforcementPolicy(msg)
    return frozenset(rule_ids)


@dataclass(frozen=True, slots=True)
class EnforcementPolicy:
    """One deterministic policy for classifying QueryGuard findings.

    Rule-level fields are intentionally supported here even though severity-based
    policy is the normal configuration.  That keeps a future narrowly-scoped
    exemption from needing a second policy implementation.  Explicit ignored and
    warning rules take precedence over both rule and severity blocking; explicit
    block rules then take precedence over severity exclusions.
    """

    blocking_severities: frozenset[Severity] = field(
        default_factory=lambda: DEFAULT_BLOCKING_SEVERITIES
    )
    ignored_severities: frozenset[Severity] = field(default_factory=frozenset)
    blocking_rule_ids: frozenset[str] = field(default_factory=frozenset)
    warning_rule_ids: frozenset[str] = field(default_factory=frozenset)
    ignored_rule_ids: frozenset[str] = field(default_factory=frozenset)

    _STATUS_BY_BLOCKING: ClassVar[dict[bool, EnforcementStatus]] = {
        False: EnforcementStatus.PASS,
        True: EnforcementStatus.BLOCKED,
    }

    def should_block(self, finding: Finding) -> bool:
        """Whether this structured finding blocks under this policy.

        Only ``Finding.rule_id`` and ``Finding.severity`` participate.  In
        particular, title, confidence, Markdown, and any LLM-authored explanation
        are deliberately absent from this decision.
        """
        if finding.rule_id in self.ignored_rule_ids | self.warning_rule_ids:
            return False
        if finding.rule_id in self.blocking_rule_ids:
            return True
        if finding.severity in self.ignored_severities:
            return False
        return finding.severity in self.blocking_severities

    def blocking_findings(self, findings: Sequence[Finding]) -> list[Finding]:
        """Return every blocking finding, preserving deterministic rank order."""
        return [finding for finding in findings if self.should_block(finding)]

    def evaluate(self, report: Report, *, findings: Sequence[Finding] | None = None) -> ReviewResult:
        """Produce a complete enforcement result from deterministic findings.

        ``findings`` exists for the runner's report cap: enforcement must inspect
        all findings, including lower-priority ones omitted from a long comment.
        """
        authoritative_findings = list(report.findings if findings is None else findings)
        blocking = self.blocking_findings(authoritative_findings)
        warnings = [finding for finding in authoritative_findings if finding not in blocking]
        return ReviewResult(
            report=report,
            findings=authoritative_findings,
            blocking_findings=blocking,
            warning_findings=warnings,
            status=self._STATUS_BY_BLOCKING[bool(blocking)],
        )


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Report plus the independent, deterministic enforcement decision."""

    report: Report
    findings: list[Finding]
    blocking_findings: list[Finding]
    warning_findings: list[Finding]
    status: EnforcementStatus
