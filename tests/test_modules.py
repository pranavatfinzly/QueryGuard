"""Placeholder-state tests.

These assert that every pipeline module imports cleanly and that its entry points
are still unimplemented. As each stage lands, replace the corresponding case with
real behavioural tests.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from modules import dynamic_analysis, extractor, github_client, llm_layer, static_rules
from modules.models import ExtractedQuery, Provenance, QueryKind

UNIMPLEMENTED: list[tuple[Callable[..., Any], tuple[Any, ...]]] = [
    (extractor.extract_queries, ("",)),
    (extractor.extract_from_sql, ("q.sql", "")),
    (extractor.extract_from_java, ("Repo.java", "")),
    (static_rules.run_static_rules, ([],)),
    (dynamic_analysis.explain_analyze, (None, None)),
    (dynamic_analysis.analyze_plan, (None, {})),
    (dynamic_analysis.simulate_indexes, (None, None, {})),
    (llm_layer.detect_n_plus_one, ([], "")),
    (github_client.fetch_pull_request, ("acme/x", 1)),
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


def test_rule_registry_starts_empty() -> None:
    assert static_rules.RULES == []


def test_comment_marker_is_stable() -> None:
    # The marker is what makes the PR comment idempotent — changing it orphans
    # every comment QueryGuard has already posted.
    assert github_client.COMMENT_MARKER == "<!-- queryguard:report -->"


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
