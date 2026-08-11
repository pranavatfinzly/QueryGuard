"""Run and report contracts — the pipeline's outermost inputs and output."""

from __future__ import annotations

from pydantic import Field

from queryguard.models.base import Contract
from queryguard.models.finding import Finding
from queryguard.models.query import ExtractedQuery


class RunContext(Contract):
    """Identifies the PR under analysis and the run itself."""

    run_id: str
    repo: str = Field(description='Owner/name, e.g. "acme/billing-service".')
    pr_number: int
    base_sha: str | None = None
    head_sha: str | None = None


class Report(Contract):
    """Merged output of every stage; input to the Markdown renderer."""

    context: RunContext
    queries: list[ExtractedQuery] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    degraded_stages: list[str] = Field(
        default_factory=list,
        description="Stages that failed soft; surfaced in the report as caveats.",
    )
    comment_id: int | None = Field(
        default=None,
        description="The ID of the comment posted to the pull request, if any.",
    )
    omitted_findings: int = Field(
        default=0,
        ge=0,
        description="Lower-priority findings dropped by the report cap. They were "
        "still found and ranked — only the comment's length was bounded — so this "
        "is surfaced rather than left for the count in `findings` to misstate as "
        "the total.",
    )
