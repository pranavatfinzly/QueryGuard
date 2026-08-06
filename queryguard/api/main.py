"""QueryGuard FastAPI service.

Run locally::

    uvicorn queryguard.api.main:app --reload

Endpoints:

- ``GET  /health``  — liveness probe.
- ``POST /analyze`` — run the review pipeline over the SQL in a pull request.

The route validates the request, hands it to
:class:`~queryguard.pipeline.runner.AnalysisRunner`, and shapes the response. The
ordering of the stages and their failure handling belong to the runner, so this
module holds no analysis logic.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from queryguard.api.deps import get_analysis_runner
from queryguard.models import Report, SqlSource
from queryguard.pipeline.runner import AnalysisRunner

#: Provenance path recorded for SQL passed inline as ``sql``, which has no file of
#: its own. Findings from it still anchor to a line — the line within the snippet.
INLINE_SQL_PATH = "inline.sql"

app = FastAPI(
    title="QueryGuard",
    version="0.1.0",
    description="Reviews SQL, JPQL/HQL, JPA native queries, and Spring Data "
    "derived methods on a pull request for performance problems.",
)


class AnalyzeRequest(BaseModel):
    """Input to a review run.

    Supply the SQL directly — as ``sql`` for a single snippet, or as ``sql_files``
    for several named sources — to analyze it without calling GitHub. This is the
    path local runs and tests use.
    """

    repo: str = Field(description='Owner/name, e.g. "acme/billing-service".')
    pr_number: int = Field(gt=0)
    sql: str | None = Field(
        default=None,
        description="SQL to analyze, one or more statements. Reported against "
        f"`{INLINE_SQL_PATH}`. Analyzed before `sql_files`.",
    )
    sql_files: list[SqlSource] = Field(
        default_factory=list,
        description="Named SQL sources. Each is extracted independently, so one "
        "file that cannot be parsed does not cost the others.",
    )
    diff: str | None = Field(
        default=None,
        description="Unified diff. Not yet analyzable — extracting queries from a "
        "diff is stage 2's dispatch, which is unimplemented.",
    )
    post_comment: bool = Field(
        default=False,
        description="Whether to upsert the tagged report comment on the PR. Not yet "
        "available — Markdown rendering and the GitHub upsert are unimplemented.",
    )

    def sql_sources(self) -> list[SqlSource]:
        """Every SQL source this request carries, in the order they are analyzed."""
        if self.sql is None:
            return self.sql_files
        return [SqlSource(path=INLINE_SQL_PATH, content=self.sql), *self.sql_files]


class AnalyzeResponse(BaseModel):
    """Result of a review run."""

    run_id: str
    status: Literal["completed", "degraded"] = Field(
        description='"degraded" when a stage failed soft; the report is still valid, '
        "but it covers less than was submitted. See `report.degraded_stages`.",
    )
    report: Report
    comment_id: int | None = Field(
        default=None,
        description="Set when the report was posted to the PR.",
    )

    @classmethod
    def from_report(cls, report: Report) -> AnalyzeResponse:
        """Wrap a finished report, deriving the run's status from what degraded."""
        return cls(
            run_id=report.context.run_id,
            status="degraded" if report.degraded_stages else "completed",
            report=report,
        )


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok", version=app.version)


@app.post("/analyze", response_model=AnalyzeResponse, tags=["analysis"])
def analyze(
    request: AnalyzeRequest,
    runner: Annotated[AnalysisRunner, Depends(get_analysis_runner)],
) -> AnalyzeResponse:
    """Review one pull request's SQL.

    Runs the two implemented stages — extract, then the static rules — and returns
    the ranked findings. Malformed SQL degrades the run rather than failing it: the
    offending source is reported as unanalyzable in ``report.queries`` and named in
    ``report.degraded_stages``, and every other source is still analyzed.

    ``diff`` and ``post_comment`` are rejected with 501 rather than ignored. Both
    depend on stages that do not exist yet (diff dispatch in stage 2; Markdown
    rendering and the comment upsert in stage 8), and answering "no problems found"
    to a request whose input was never read is the one failure mode a review bot
    cannot have.
    """
    if request.diff is not None and request.diff.strip():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Analyzing a diff is not implemented yet. Supply the SQL directly "
            "via `sql` or `sql_files`.",
        )
    if request.post_comment:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Posting the report to the PR is not implemented yet. Omit "
            "`post_comment` to receive the report in the response.",
        )

    report = runner.run(
        repo=request.repo,
        pr_number=request.pr_number,
        sources=request.sql_sources(),
    )
    return AnalyzeResponse.from_report(report)
