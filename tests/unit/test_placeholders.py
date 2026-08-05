"""Placeholder-state tests.

These assert that every pipeline module imports cleanly and that its entry points
are still unimplemented. As each stage lands, replace the corresponding case with
real behavioural tests.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from queryguard.db import provision, session
from queryguard.integrations import claude, github
from queryguard.models import ExtractedQuery, Provenance, QueryKind
from queryguard.pipeline import explain, hypopg, ingest, nplusone, report, static_rules
from queryguard.pipeline import extract

UNIMPLEMENTED: list[tuple[Callable[..., Any], tuple[Any, ...]]] = [
    (ingest.ingest_pull_request, ("acme/x", 1)),
    (extract.extract_queries, ("",)),
    (extract.extract_from_sql, ("q.sql", "")),
    (extract.extract_from_java, ("Repo.java", "")),
    (extract.parse_derived_method, ("findByCustomerId", "Order", "Repo.java")),
    (static_rules.run_static_rules, ([],)),
    (explain.explain_analyze, (None, None)),
    (explain.analyze_plan, (None, {})),
    (hypopg.simulate_indexes, (None, None, {})),
    (nplusone.detect_n_plus_one, ([], "")),
    (report.rank_findings, ([],)),
    (report.render_markdown, (None,)),
    (github.fetch_pull_request, ("acme/x", 1)),
    (claude.request_findings, ("sys", "user")),
]


@pytest.mark.parametrize(
    ("func", "args"),
    UNIMPLEMENTED,
    ids=[f"{f.__module__}.{f.__name__}" for f, _ in UNIMPLEMENTED],
)
def test_entry_point_is_not_implemented_yet(
    func: Callable[..., Any], args: tuple[Any, ...]
) -> None:
    with pytest.raises(NotImplementedError):
        func(*args)


@pytest.mark.parametrize(
    "context_manager",
    [provision.provision_reference_db, session.rollback_transaction],
    ids=["provision_reference_db", "rollback_transaction"],
)
def test_context_manager_stage_is_not_implemented_yet(
    context_manager: Callable[..., Any],
) -> None:
    # These are @contextmanager generators, so the body does not run until the
    # `with` is entered — calling them alone raises nothing.
    with pytest.raises(NotImplementedError), context_manager(None):
        pass  # pragma: no cover


def test_rule_registry_starts_empty() -> None:
    assert static_rules.RULES == []


def test_comment_marker_is_stable() -> None:
    # The marker is what makes the PR comment idempotent — changing it orphans
    # every comment QueryGuard has already posted.
    assert github.COMMENT_MARKER == "<!-- queryguard:report -->"


def test_default_model_is_the_documented_one() -> None:
    assert claude.MODEL == "claude-opus-5"


def test_extracted_query_records_parse_failures() -> None:
    query = ExtractedQuery(
        id="q1",
        kind=QueryKind.RAW_SQL,
        text="SELECT FROM WHERE",
        provenance=Provenance(file="migrations/001.sql", line=3),
        parse_error="unexpected token",
    )

    assert query.normalized is None
    assert query.parse_error == "unexpected token"


def test_models_are_re_exported_at_package_level() -> None:
    # Callers import from `queryguard.models`; the split across query/finding/
    # report modules is an authoring detail they should not have to track.
    from queryguard.models import Finding, Report, Severity, Suggestion

    assert Finding.__name__ == "Finding"
    assert Report.__name__ == "Report"
    assert Severity.CRITICAL == "critical"
    assert Suggestion.__name__ == "Suggestion"
