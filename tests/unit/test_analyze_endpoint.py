"""Behavioural tests for ``POST /analyze`` now that the static path is wired.

These assert what a caller sees: the findings, their ranking, their provenance, and
what happens when the SQL is bad. The stage-level fail-soft contracts are tested in
``test_analysis_runner.py``; here the question is only whether the HTTP surface
tells the truth about them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from queryguard.api.deps import get_analysis_runner
from queryguard.api.main import INLINE_SQL_PATH, AnalyzeResponse, app
from queryguard.models import Report, SqlSource
from queryguard.pipeline.extract import extract_from_sql
from queryguard.pipeline.runner import AnalysisRunner

# The sandbox's healthy counterparts: named columns behind an indexed predicate, and
# a write that is actually scoped. Anything QueryGuard says about these is noise.
HEALTHY_SELECT = "SELECT id, order_number, status FROM orders WHERE placed_at >= :since"
HEALTHY_UPDATE = "UPDATE customers SET loyalty_tier = 'gold' WHERE lifetime_value >= 1000"


def post_sql(client: TestClient, sql: str) -> dict[str, Any]:
    """Analyze one SQL snippet and return the decoded body, asserting a 200."""
    response = client.post(
        "/analyze",
        json={"repo": "acme/billing-service", "pr_number": 42, "sql": sql},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
def use_runner() -> Iterator[Callable[[AnalysisRunner], None]]:
    """Swap the injected runner for one test, then put the real one back.

    Proves the seam in ``api/deps.py`` is real: nothing in the route reaches past
    ``Depends`` to build its own pipeline.
    """

    def _use(runner: AnalysisRunner) -> None:
        app.dependency_overrides[get_analysis_runner] = lambda: runner

    yield _use
    app.dependency_overrides.pop(get_analysis_runner, None)


def test_select_star_is_reported_as_medium(client: TestClient) -> None:
    body = post_sql(client, "SELECT * FROM orders WHERE id = 1")

    findings = body["report"]["findings"]
    assert [finding["rule_id"] for finding in findings] == ["select-star"]
    assert findings[0]["severity"] == "medium"
    # A finding a reviewer cannot act on is not worth posting.
    assert findings[0]["impact"]
    assert findings[0]["suggestions"][0]["description"]
    assert body["status"] == "completed"


def test_unqualified_update_is_reported_as_critical(client: TestClient) -> None:
    body = post_sql(client, "UPDATE orders SET status = 'shipped'")

    findings = body["report"]["findings"]
    assert [finding["rule_id"] for finding in findings] == ["missing-where"]
    assert findings[0]["severity"] == "critical"


def test_every_statement_in_a_snippet_is_analyzed(client: TestClient) -> None:
    body = post_sql(
        client,
        "SELECT * FROM orders WHERE id = 1;\n"
        "UPDATE customers SET loyalty_tier = 'gold';\n"
        "SELECT id FROM shipments;",
    )

    # Three statements in, three candidates out, each with its own identity.
    assert [query["id"] for query in body["report"]["queries"]] == [
        f"{INLINE_SQL_PATH}:1",
        f"{INLINE_SQL_PATH}:2",
        f"{INLINE_SQL_PATH}:3",
    ]

    by_query = {finding["query_id"]: finding["rule_id"] for finding in body["report"]["findings"]}
    assert by_query == {
        f"{INLINE_SQL_PATH}:1": "select-star",
        f"{INLINE_SQL_PATH}:2": "missing-where",
        f"{INLINE_SQL_PATH}:3": "no-limit",
    }

    # Data loss outranks slowness, whatever order the statements were written in.
    assert body["report"]["findings"][0]["rule_id"] == "missing-where"


def test_healthy_sql_produces_no_findings(client: TestClient) -> None:
    body = post_sql(client, f"{HEALTHY_SELECT};\n{HEALTHY_UPDATE};")

    assert body["report"]["findings"] == []
    assert body["report"]["degraded_stages"] == []
    assert body["status"] == "completed"
    # Silence has to mean "analyzed and clean", not "never looked".
    assert len(body["report"]["queries"]) == 2


def test_empty_sql_returns_an_empty_report(client: TestClient) -> None:
    body = post_sql(client, "")

    assert body["report"]["queries"] == []
    assert body["report"]["findings"] == []
    assert body["report"]["degraded_stages"] == []
    assert body["status"] == "completed"


def test_unparseable_sql_degrades_instead_of_failing(client: TestClient) -> None:
    response = client.post(
        "/analyze",
        json={"repo": "acme/billing-service", "pr_number": 42, "sql": "SELECT FROM WHERE"},
    )

    # Fail soft: a query QueryGuard cannot read is a caveat in the report, not a
    # 500 and not a failed PR check.
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "degraded"
    assert body["report"]["degraded_stages"] == [f"extract:{INLINE_SQL_PATH}"]
    assert body["report"]["findings"] == []

    # The candidate survives with the reason attached, so the report can say which
    # statement went unanalyzed rather than quietly dropping it.
    (query,) = body["report"]["queries"]
    assert query["parse_error"]
    assert "Traceback" not in response.text


def test_one_unparseable_source_does_not_stop_the_others(client: TestClient) -> None:
    response = client.post(
        "/analyze",
        json={
            "repo": "acme/billing-service",
            "pr_number": 42,
            "sql_files": [
                {"path": "migrations/001_orders.sql", "content": "SELECT * FROM orders"},
                {"path": "migrations/002_broken.sql", "content": "SELECT FROM WHERE"},
                {"path": "migrations/003_customers.sql", "content": "DELETE FROM customers"},
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()

    # The two readable files are analyzed in full; only the broken one is lost.
    assert {finding["provenance"]["file"] for finding in body["report"]["findings"]} == {
        "migrations/001_orders.sql",
        "migrations/003_customers.sql",
    }
    assert body["report"]["degraded_stages"] == ["extract:migrations/002_broken.sql"]
    assert body["status"] == "degraded"


def test_line_numbers_match_what_the_extractor_recorded(client: TestClient) -> None:
    sql = "SELECT * FROM orders;\n\n\nUPDATE customers SET loyalty_tier = 'gold';"

    body = post_sql(client, sql)

    # Anchored to the statement, not the top of the snippet — a report that points at
    # line 1 for everything cannot be reviewed against the diff.
    expected = [query.provenance.line for query in extract_from_sql(INLINE_SQL_PATH, sql)]
    assert expected == [1, 4]
    assert [query["provenance"]["line"] for query in body["report"]["queries"]] == expected

    # Every finding inherits the line of the statement it was raised against.
    lines_by_rule = {
        finding["rule_id"]: finding["provenance"]["line"] for finding in body["report"]["findings"]
    }
    assert lines_by_rule == {"select-star": 1, "no-limit": 1, "missing-where": 4}


def test_response_body_matches_the_declared_models(client: TestClient) -> None:
    body = post_sql(client, "SELECT * FROM orders")

    response_model = AnalyzeResponse.model_validate(body)
    assert response_model.run_id == body["run_id"]
    assert response_model.report.findings

    # No extra keys and no lossy fields: what the endpoint serializes is exactly a
    # Report, which is what the Markdown renderer will later be handed.
    report = Report.model_validate(body["report"])
    assert report.model_dump(mode="json") == body["report"]


def test_the_run_id_is_logged_with_the_run_s_shape(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="queryguard.pipeline.runner"):
        body = post_sql(client, "SELECT * FROM orders WHERE id = 1")

    run_id = body["run_id"]
    (record,) = [rec for rec in caplog.records if getattr(rec, "run_id", None) == run_id]

    # In the message as well as in `extra`: a plain-text log line is what someone
    # greps when correlating a report back to the run that produced it.
    assert run_id in record.getMessage()
    assert {
        field: getattr(record, field, None) for field in ("number_of_queries", "number_of_findings")
    } == {"number_of_queries": 1, "number_of_findings": 1}
    assert getattr(record, "processing_time_ms", -1.0) >= 0


def test_run_ids_are_unique_per_request(client: TestClient) -> None:
    first = post_sql(client, "SELECT 1")["run_id"]
    second = post_sql(client, "SELECT 1")["run_id"]

    assert first != second


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"diff": "--- a/x.sql\n+++ b/x.sql\n"}, id="diff"),
        pytest.param({"post_comment": True}, id="post_comment"),
    ],
)
def test_unimplemented_options_are_refused_rather_than_ignored(
    client: TestClient, payload: dict[str, Any]
) -> None:
    response = client.post(
        "/analyze",
        json={"repo": "acme/billing-service", "pr_number": 42, **payload},
    )

    # Answering "no problems found" to input that was never read is the one failure
    # mode a review bot cannot have, so this is 501 rather than an empty report.
    assert response.status_code == 501
    assert response.json()["detail"]


def test_validation_errors_are_still_preserved(client: TestClient) -> None:
    response = client.post(
        "/analyze",
        json={"repo": "acme/x", "pr_number": 0, "sql": "SELECT 1"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "pr_number"]


def test_the_route_uses_the_injected_runner(
    client: TestClient, use_runner: Callable[[AnalysisRunner], None]
) -> None:
    class FixedRunIdRunner(AnalysisRunner):
        def run(
            self,
            *,
            repo: str,
            pr_number: int,
            sources: Sequence[SqlSource],
            run_id: str | None = None,
        ) -> Report:
            return super().run(
                repo=repo, pr_number=pr_number, sources=sources, run_id="fixed-run-id"
            )

    use_runner(FixedRunIdRunner())

    assert post_sql(client, "SELECT * FROM orders")["run_id"] == "fixed-run-id"


def test_an_exploding_runner_does_not_leak_a_stack_trace(
    use_runner: Callable[[AnalysisRunner], None],
) -> None:
    class ExplodingRunner(AnalysisRunner):
        def run(
            self,
            *,
            repo: str,
            pr_number: int,
            sources: Sequence[SqlSource],
            run_id: str | None = None,
        ) -> Report:
            raise RuntimeError("connection string postgres://user:hunter2@db/prod")

    use_runner(ExplodingRunner())

    # The runner is exhaustively fail-soft, so this should be unreachable — but if it
    # ever is reached, the response must not carry the traceback or anything the
    # exception was holding.
    with TestClient(app, raise_server_exceptions=False) as unguarded:
        response = unguarded.post(
            "/analyze",
            json={"repo": "acme/x", "pr_number": 1, "sql": "SELECT 1"},
        )

    assert response.status_code == 500
    assert "Traceback" not in response.text
    assert "hunter2" not in response.text
