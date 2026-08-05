"""QueryGuard FastAPI service.

Run locally::

    uvicorn queryguard.api.main:app --reload

Endpoints:

- ``GET  /health``  — liveness probe.
- ``POST /analyze`` — run the review pipeline for one pull request.

The pipeline stages live in :mod:`queryguard.pipeline` and are placeholders; see
the wiring TODO in :func:`analyze`.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from queryguard.models import Finding, Report, RunContext

app = FastAPI(
    title="QueryGuard",
    version="0.1.0",
    description="Reviews SQL, JPQL/HQL, JPA native queries, and Spring Data "
    "derived methods on a pull request for performance problems.",
)


class AnalyzeRequest(BaseModel):
    """Input to a review run.

    Supply ``diff`` to analyze a diff directly without calling GitHub — this is
    the path local runs and tests use.
    """

    repo: str = Field(description='Owner/name, e.g. "acme/billing-service".')
    pr_number: int = Field(gt=0)
    diff: str | None = Field(
        default=None,
        description="Unified diff. When omitted, it is fetched via the GitHub API.",
    )
    post_comment: bool = Field(
        default=False,
        description="Whether to upsert the tagged report comment on the PR.",
    )


class AnalyzeResponse(BaseModel):
    """Result of a review run."""

    run_id: str
    status: Literal["completed", "degraded", "not_implemented"]
    report: Report
    comment_id: int | None = Field(
        default=None,
        description="Set when the report was posted to the PR.",
    )


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok", version=app.version)


@app.post("/analyze", response_model=AnalyzeResponse, tags=["analysis"])
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Review one pull request's queries.

    Returns an empty report until the pipeline stages are implemented. Stage
    wiring, in order (see CLAUDE.md):

    1. ``pipeline.ingest.ingest_pull_request`` when ``diff`` is None
    2. ``pipeline.extract.extract_queries``
    3. ``pipeline.static_rules.run_static_rules``
    4. ``db.provision.provision_reference_db``
    5. ``pipeline.explain.explain_analyze`` + ``analyze_plan``
    6. ``pipeline.hypopg.simulate_indexes``
    7. ``pipeline.nplusone.detect_n_plus_one``
    8. ``pipeline.report.render_markdown``, then
       ``integrations.github.upsert_report_comment`` when ``post_comment`` is set

    Each stage fails soft: on error, record the stage name in
    ``report.degraded_stages`` and continue rather than failing the PR check.
    """
    context = RunContext(
        run_id=str(uuid.uuid4()),
        repo=request.repo,
        pr_number=request.pr_number,
    )
    findings: list[Finding] = []

    return AnalyzeResponse(
        run_id=context.run_id,
        status="not_implemented",
        report=Report(context=context, findings=findings),
    )
