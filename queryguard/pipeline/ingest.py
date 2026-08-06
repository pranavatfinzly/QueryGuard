"""Stage 1 — Ingest.

Turns a PR event into a :class:`RunContext` and the diff the rest of the pipeline
reads. GitHub access itself belongs to
:mod:`queryguard.integrations.github`; this stage only orchestrates it, so no
other stage needs to know GitHub exists.
"""

from __future__ import annotations

from queryguard.models.report import RunContext

__all__ = ["ingest_pull_request"]


def ingest_pull_request(repo: str, pr_number: int) -> tuple[RunContext, str]:
    """Resolve a PR to its run context and unified diff.

    Returns the context (including base/head SHAs) alongside the diff text.
    """
    raise NotImplementedError("ingest.ingest_pull_request is not implemented yet")
