"""Stage 1 — Ingest.

Turns a PR event into a :class:`RunContext` and the sources the rest of the
pipeline reads. GitHub access itself belongs to
:mod:`queryguard.integrations.github` and diff interpretation to
:mod:`queryguard.pipeline.diff`; this stage only orchestrates the two, so no
other stage needs to know GitHub exists.

Three modules for one stage looks like a lot until you ask what each is allowed
to do. ``github`` is the only one that may open a socket, ``diff`` is the only
one that may decide what a patch means, and this is the only one that knows they
go together in that order. Splitting them is what lets the interesting half —
which files become sources, which are skipped, which degrade — be tested from a
recorded payload with no credentials and no network.
"""

from __future__ import annotations

from github import Github

from queryguard.integrations.github import (
    fetch_changed_files,
    fetch_pull_request,
    new_client,
    read_head_file,
)
from queryguard.models.diff import DiffIngest
from queryguard.pipeline.diff import build_sources
from queryguard.pipeline.extract import ExtractorRegistry

__all__ = ["ingest_pull_request"]


def ingest_pull_request(
    repo: str,
    pr_number: int,
    *,
    run_id: str | None = None,
    client: Github | None = None,
    registry: ExtractorRegistry | None = None,
) -> DiffIngest:
    """Resolve a PR to its run context and the sources stage 2 will read.

    Returns a :class:`~queryguard.models.diff.DiffIngest`: the context including
    base and head SHAs, one
    :class:`~queryguard.models.query.SourceFile` per changed file an extractor
    claims, the files deliberately skipped and why, and the files that should
    have been readable and were not.

    All three lists, rather than the sources alone, because a review bot that
    cannot say what it did *not* look at is a review bot whose silence means
    nothing. Deletions and unsupported languages land in ``skipped`` — those are
    not failures — while a file that raises lands in ``degraded_stages`` and
    costs only itself.

    The client is built once here and threaded through every call, so a run
    authenticates once however many files it reads. Both it and ``registry`` are
    injectable, which is how the tests drive this end to end against the recorded
    fixture with no token in sight.
    """
    resolved = client if client is not None else new_client()

    context = fetch_pull_request(repo, pr_number, run_id=run_id, client=resolved)
    changed = fetch_changed_files(context, client=resolved)

    return build_sources(
        context,
        changed,
        lambda path: read_head_file(context, path, client=resolved),
        registry=registry,
    )
