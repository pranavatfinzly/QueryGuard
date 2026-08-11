"""Deterministic merge-enforcement policy tests."""

from __future__ import annotations

import pytest

from queryguard.config import Settings
from queryguard.models import Finding, Provenance, Report, RunContext, Severity
from queryguard.policy import EnforcementPolicy, EnforcementStatus, InvalidEnforcementPolicy


def context() -> RunContext:
    return RunContext(run_id="r", repo="acme/billing", pr_number=1)


def finding(
    severity: Severity,
    *,
    rule_id: str = "example-rule",
    title: str | None = None,
    explanation: str = "deterministic evidence",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        title=title if title is not None else f"{severity.name} finding",
        explanation=explanation,
        impact="impact",
        provenance=Provenance(file="a.sql", line=1),
    )


def evaluate(*findings: Finding, policy: EnforcementPolicy | None = None) -> EnforcementStatus:
    report = Report(context=context(), findings=list(findings))
    result = (policy if policy is not None else EnforcementPolicy()).evaluate(report)
    return result.status


@pytest.mark.parametrize("severity", [Severity.CRITICAL, Severity.HIGH])
def test_default_policy_blocks_critical_and_high(severity: Severity) -> None:
    assert evaluate(finding(severity)) is EnforcementStatus.BLOCKED


@pytest.mark.parametrize("severity", [Severity.MEDIUM, Severity.LOW, Severity.INFO])
def test_default_policy_allows_medium_low_and_info(severity: Severity) -> None:
    assert evaluate(finding(severity)) is EnforcementStatus.PASS


def test_multiple_findings_with_one_high_are_blocked() -> None:
    result = EnforcementPolicy().evaluate(
        Report(
            context=context(),
            findings=[
                finding(Severity.INFO),
                finding(Severity.MEDIUM),
                finding(Severity.HIGH),
            ],
        )
    )

    assert result.status is EnforcementStatus.BLOCKED
    assert [item.severity for item in result.blocking_findings] == [Severity.HIGH]
    assert [item.severity for item in result.warning_findings] == [
        Severity.INFO,
        Severity.MEDIUM,
    ]


def test_no_findings_pass() -> None:
    assert EnforcementPolicy().evaluate(Report(context=context())).status is EnforcementStatus.PASS


def test_custom_blocking_severity_configuration_works() -> None:
    policy = Settings.isolated(block_severities=" medium , low ").enforcement_policy()

    assert evaluate(finding(Severity.MEDIUM), policy=policy) is EnforcementStatus.BLOCKED
    assert evaluate(finding(Severity.LOW), policy=policy) is EnforcementStatus.BLOCKED
    assert evaluate(finding(Severity.HIGH), policy=policy) is EnforcementStatus.PASS


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_or_absent_blocking_severities_keep_the_safe_default(value: str | None) -> None:
    settings = Settings.isolated() if value is None else Settings.isolated(block_severities=value)
    policy = settings.enforcement_policy()

    assert evaluate(finding(Severity.HIGH), policy=policy) is EnforcementStatus.BLOCKED


def test_invalid_severity_configuration_fails_clearly() -> None:
    with pytest.raises(InvalidEnforcementPolicy, match="QUERYGUARD_BLOCK_SEVERITIES"):
        Settings.isolated(block_severities="HIGH,URGENT").enforcement_policy()


def test_empty_severity_name_fails_clearly() -> None:
    with pytest.raises(InvalidEnforcementPolicy, match="empty severity name"):
        Settings.isolated(block_severities="HIGH,,CRITICAL").enforcement_policy()


def test_prefixed_environment_names_build_the_policy() -> None:
    policy = Settings.from_mapping({"QUERYGUARD_BLOCK_SEVERITIES": "MEDIUM"}).enforcement_policy()

    assert evaluate(finding(Severity.MEDIUM), policy=policy) is EnforcementStatus.BLOCKED
    assert evaluate(finding(Severity.HIGH), policy=policy) is EnforcementStatus.PASS


def test_rule_level_overrides_are_authoritative() -> None:
    policy = Settings.isolated(
        block_rules="select-star",
        warn_rules="no-limit",
        ignore_rules="missing-where",
    ).enforcement_policy()

    assert evaluate(finding(Severity.MEDIUM, rule_id="select-star"), policy=policy) is (
        EnforcementStatus.BLOCKED
    )
    assert evaluate(finding(Severity.HIGH, rule_id="no-limit"), policy=policy) is (
        EnforcementStatus.PASS
    )
    assert evaluate(finding(Severity.CRITICAL, rule_id="missing-where"), policy=policy) is (
        EnforcementStatus.PASS
    )


def test_llm_authored_prose_cannot_make_a_high_finding_pass() -> None:
    high = finding(
        Severity.HIGH,
        title="Groq says this is safe",
        explanation="This may not be problematic.",
    )

    assert evaluate(high) is EnforcementStatus.BLOCKED
