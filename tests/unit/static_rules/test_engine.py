"""RuleEngine — parsing, aggregation, ranking, failure isolation, log hygiene."""

from __future__ import annotations

import logging

import pytest

from queryguard.models.finding import Finding, Severity
from queryguard.models.query import ExtractedQuery, Provenance, QueryKind
from queryguard.pipeline.static_rules import (
    RULES,
    RuleContext,
    RuleEngine,
    run_static_rules,
)
from queryguard.pipeline.static_rules.engine import (
    _CommandFallbackFilter,
    silence_sqlglot_fallback_warnings,
)


def _query(sql: str, query_id: str = "q1", **kwargs: object) -> ExtractedQuery:
    return ExtractedQuery(
        id=query_id,
        kind=QueryKind.RAW_SQL,
        text=sql,
        provenance=Provenance(file="Repo.java", line=1),
        **kwargs,  # type: ignore[arg-type]
    )


class _ExplodingRule:
    rule_id = "exploding"

    def check(self, context: RuleContext) -> list[Finding]:
        raise ValueError("deliberate failure")


class _QuietRule:
    rule_id = "quiet"

    def check(self, context: RuleContext) -> list[Finding]:
        return []


def test_registry_holds_every_implemented_rule() -> None:
    assert sorted(rule.rule_id for rule in RULES) == [
        "missing-where",
        "no-limit",
        "non-sargable",
        "select-star",
        "unindexed-filter",
    ]


def test_aggregates_findings_across_rules_and_queries() -> None:
    findings = RuleEngine().analyze(
        [_query("SELECT * FROM orders", "q1"), _query("DELETE FROM customers", "q2")]
    )

    by_query = {finding.query_id for finding in findings}
    assert by_query == {"q1", "q2"}
    assert {finding.rule_id for finding in findings} >= {
        "select-star",
        "no-limit",
        "missing-where",
    }


def test_ranks_findings_worst_first() -> None:
    findings = RuleEngine().analyze(
        [_query("SELECT * FROM orders", "q1"), _query("DELETE FROM customers", "q2")]
    )

    severities = [finding.severity for finding in findings]
    assert severities[0] is Severity.CRITICAL
    assert severities == sorted(
        severities,
        key=[
            Severity.CRITICAL,
            Severity.HIGH,
            Severity.MEDIUM,
            Severity.LOW,
            Severity.INFO,
        ].index,
    )


def test_skips_queries_the_extract_stage_already_failed_on() -> None:
    # Re-reporting a parse failure as a rule finding would double-count one problem.
    findings = RuleEngine().analyze(
        [_query("SELECT FROM WHERE", "q1", parse_error="unexpected token")]
    )

    assert findings == []


def test_skips_unparseable_queries_without_raising() -> None:
    findings = RuleEngine().analyze([_query("this is not sql at all !!", "q1")])

    assert findings == []


def test_skips_opaque_command_statements() -> None:
    # sqlglot parses these to a Command node with no structure to inspect. Applying
    # rules to the raw text instead would mean regexing SQL.
    findings = RuleEngine().analyze([_query("SHOW search_path", "q1")])

    assert findings == []


def test_one_failing_rule_does_not_lose_the_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from queryguard.pipeline.static_rules import SelectStarRule

    engine = RuleEngine(rules=[_ExplodingRule(), SelectStarRule()])

    with caplog.at_level(logging.ERROR):
        findings = engine.analyze([_query("SELECT * FROM orders")])

    assert [finding.rule_id for finding in findings] == ["select-star"]
    assert "exploding" in caplog.text


def test_failing_rule_logs_the_query_it_failed_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR):
        RuleEngine(rules=[_ExplodingRule()]).analyze([_query("SELECT 1", "q-specific")])

    assert "q-specific" in caplog.text


def test_explicit_rule_list_overrides_the_registry() -> None:
    assert RuleEngine(rules=[_QuietRule()]).analyze([_query("SELECT * FROM orders")]) == []


def test_run_static_rules_is_the_stage_entry_point() -> None:
    findings = run_static_rules([_query("SELECT * FROM orders")])

    assert {finding.rule_id for finding in findings} == {"select-star", "no-limit"}


def test_sqlglot_command_fallback_warning_is_filtered() -> None:
    # The filter is asserted directly as well as end to end: it is installed on a
    # process-global logger, so once any engine exists the end-to-end assertion can
    # no longer distinguish "filtered" from "never logged".
    fallback = logging.LogRecord(
        name="sqlglot",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="'SHOW search_path' contains unsupported syntax. Falling back to parsing as a 'Command'.",
        args=(),
        exc_info=None,
    )
    unrelated = logging.LogRecord(
        name="sqlglot",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="something a maintainer would actually want to see",
        args=(),
        exc_info=None,
    )
    log_filter = _CommandFallbackFilter()

    assert log_filter.filter(fallback) is False
    assert log_filter.filter(unrelated) is True


def test_engine_suppresses_the_warning_in_practice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = RuleEngine()

    with caplog.at_level(logging.WARNING, logger="sqlglot"):
        engine.analyze([_query("SHOW search_path", "q1"), _query("SET ROLE 'x'", "q2")])

    assert "unsupported syntax" not in caplog.text


def test_installing_the_filter_twice_does_not_stack_it() -> None:
    silence_sqlglot_fallback_warnings()
    silence_sqlglot_fallback_warnings()
    RuleEngine()
    RuleEngine()

    installed = [
        existing
        for existing in logging.getLogger("sqlglot").filters
        if isinstance(existing, _CommandFallbackFilter)
    ]
    assert len(installed) == 1
