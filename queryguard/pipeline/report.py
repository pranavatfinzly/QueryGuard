"""Stage 8 — Report rendering.

Merges static findings, plan findings, index suggestions, and N+1 findings into a
single ranked Markdown report: severity, evidence (plan excerpts, cost deltas),
and a suggested fix per finding.

Rendering is deliberately a pure function of the :class:`Report` model — the
comment body is user-facing, so it is snapshot-tested, and that only works if the
same report always renders the same Markdown. Posting the comment belongs to
:mod:`queryguard.integrations.github`.
"""

from __future__ import annotations

from queryguard.models.finding import Finding
from queryguard.models.report import Report

__all__ = ["rank_findings", "render_markdown"]


def rank_findings(findings: list[Finding]) -> list[Finding]:
    """Order findings for presentation, most important first."""
    raise NotImplementedError("report.rank_findings is not implemented yet")


def render_markdown(report: Report) -> str:
    """Render a report as the Markdown body of the PR comment.

    The body carries :data:`queryguard.integrations.github.COMMENT_MARKER` so
    re-runs edit the existing comment instead of adding another.
    """
    raise NotImplementedError("report.render_markdown is not implemented yet")
