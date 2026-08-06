"""PyGithub wrapper — diff retrieval and idempotent comment upsert.

Two things this module owns:

- Fetching the PR diff and base/head SHAs.
- Upserting a single **idempotent, tagged** Markdown comment. The comment carries
  :data:`COMMENT_MARKER` as an HTML comment so re-runs edit the existing comment
  instead of spamming the thread.

QueryGuard comments only. It never pushes commits, edits files, or
approves/blocks a merge.
"""

from __future__ import annotations

from queryguard.models.report import Report, RunContext

__all__ = ["COMMENT_MARKER", "fetch_diff", "fetch_pull_request", "upsert_report_comment"]

#: Hidden marker identifying QueryGuard's own comment. Changing it orphans every
#: comment already posted, so a re-run would add a second one instead of editing.
COMMENT_MARKER = "<!-- queryguard:report -->"


def fetch_pull_request(repo: str, pr_number: int) -> RunContext:
    """Resolve a PR to a run context, including base and head SHAs."""
    raise NotImplementedError("github.fetch_pull_request is not implemented yet")


def fetch_diff(context: RunContext) -> str:
    """Fetch the PR's unified diff."""
    raise NotImplementedError("github.fetch_diff is not implemented yet")


def upsert_report_comment(context: RunContext, report: Report) -> int:
    """Create or update QueryGuard's single comment on the PR.

    Searches the PR's comments for :data:`COMMENT_MARKER`; edits that comment if
    found, otherwise creates a new one. Returns the comment ID.
    """
    raise NotImplementedError("github.upsert_report_comment is not implemented yet")
