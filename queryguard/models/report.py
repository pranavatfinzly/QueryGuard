"""Run and report contracts — the pipeline's outermost inputs and output."""

from __future__ import annotations

from pydantic import BaseModel, Field

from queryguard.models.finding import Finding
from queryguard.models.query import ExtractedQuery


class RunContext(BaseModel):
    """Identifies the PR under analysis and the run itself."""

    run_id: str
    repo: str = Field(description='Owner/name, e.g. "acme/billing-service".')
    pr_number: int
    base_sha: str | None = None
    head_sha: str | None = None


class Report(BaseModel):
    """Merged output of every stage; input to the Markdown renderer."""

    context: RunContext
    queries: list[ExtractedQuery] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    degraded_stages: list[str] = Field(
        default_factory=list,
        description="Stages that failed soft; surfaced in the report as caveats.",
    )
