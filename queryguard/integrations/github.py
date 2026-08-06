"""PyGithub wrapper — diff retrieval and idempotent comment upsert.

Two things this module owns:

- Fetching the PR diff and base/head SHAs.
- Upserting a single **idempotent, tagged** Markdown comment. The comment carries
  :data:`COMMENT_MARKER` as an HTML comment so re-runs edit the existing comment
  instead of spamming the thread.

QueryGuard comments only. It never pushes commits, edits files, or
approves/blocks a merge.

Keeping the token out of everything
-----------------------------------

This is the only module that handles a GitHub credential, so it is the only place
the credential can escape from. Three rules, each backed by a test in
``tests/unit/test_github_integration.py``:

1. **The token is never interpolated into anything.** It is read from
   :mod:`queryguard.config`, handed to :class:`github.Auth.Token`, and never
   touched again. It appears in no URL, no log record, and no f-string.
2. **No exception from PyGithub is re-raised as-is.** Every call is wrapped, and
   what crosses this module's boundary is a :class:`GitHubUnavailable` whose
   message QueryGuard composed: the HTTP status, the operation, and — for a
   :class:`github.GithubException.GithubException` — GitHub's own ``message``
   field. For anything else only the exception's *type name* is carried out, so
   an unfamiliar library cannot leak its own message through us.
3. **Even those are redacted.** :func:`redact` runs over every string this module
   emits, replacing anything token-shaped. It is belt-and-braces against rule 1
   being broken later, and against a token that reached the text from somewhere
   other than our own configuration.

For what it is worth, PyGithub itself already strips ``Authorization`` from the
request headers before logging them — but that is its invariant to keep, not
ours, and rules 1–3 hold whether or not it does.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Literal

from github import Auth, Github
from github.GithubException import GithubException

from queryguard.config import get_settings
from queryguard.models.diff import ChangedFile, ChangeStatus
from queryguard.models.query import SourceFile
from queryguard.models.report import Report, RunContext
from queryguard.pipeline.diff import build_sources
from queryguard.pipeline.extract import ExtractorRegistry

__all__ = [
    "COMMENT_MARKER",
    "GitHubUnavailable",
    "fetch_changed_files",
    "fetch_diff",
    "fetch_pull_request",
    "new_client",
    "read_head_file",
    "redact",
    "upsert_report_comment",
]

logger = logging.getLogger(__name__)

#: Hidden marker identifying QueryGuard's own comment. Changing it orphans every
#: comment already posted, so a re-run would add a second one instead of editing.
COMMENT_MARKER = "<!-- queryguard:report -->"

#: What a redacted secret is replaced with. A fixed string, not a length-preserving
#: mask: how long a token is, is itself something an attacker does not have to guess.
REDACTED = "<redacted>"

#: Every credential shape GitHub currently issues — classic and fine-grained personal
#: tokens (``ghp_``, ``github_pat_``), OAuth (``gho_``), user-to-server and
#: server-to-server installation tokens (``ghu_``, ``ghs_``), and refresh tokens
#: (``ghr_``). Matched by shape rather than by value so redaction does not require
#: holding the secret in order to remove it.
_TOKEN_SHAPED = re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}")


class GitHubUnavailable(RuntimeError):
    """GitHub could not be reached, or refused a request.

    Deliberately the only exception type this module raises outward. Callers get
    one thing to catch and a message QueryGuard wrote, rather than whatever the
    HTTP stack of the day happened to put in a string.
    """


def redact(text: str) -> str:
    """Replace anything token-shaped in ``text``.

    Applied to every string this module logs or raises. It cannot make an
    arbitrary secret safe — only known GitHub credential shapes are recognized —
    which is why it is the second line of defence and not the first.
    """
    return _TOKEN_SHAPED.sub(REDACTED, text)


def new_client() -> Github:
    """Build an authenticated client from the process configuration.

    The single place a GitHub credential is read. The value goes straight into
    :class:`github.Auth.Token` and is not retained, logged, or returned.
    """
    return Github(auth=Auth.Token(get_settings().require_github_token()))


def _resolve(client: Github | None) -> Github:
    """The caller's client, or a new one built from configuration.

    Every entry point takes an optional client for the same reason the extract
    dispatcher takes an optional registry: it is a real seam. A test drives these
    functions against a fake with no token, no network, and no monkeypatching.
    """
    return client if client is not None else new_client()


def fetch_pull_request(
    repo: str,
    pr_number: int,
    *,
    run_id: str | None = None,
    client: Github | None = None,
) -> RunContext:
    """Resolve a PR to a run context, including base and head SHAs.

    ``run_id`` is generated unless supplied; callers pass one when the identifier
    comes from elsewhere — a webhook delivery ID, or a test fixture.
    """
    with _guard(f"reading {repo}#{pr_number}"):
        pull = _resolve(client).get_repo(repo).get_pull(pr_number)
        base_sha = pull.base.sha
        head_sha = pull.head.sha

    logger.info(
        "ingest: resolved %s#%d base=%s head=%s",
        repo,
        pr_number,
        base_sha,
        head_sha,
        extra={"repo": repo, "pr_number": pr_number, "base_sha": base_sha, "head_sha": head_sha},
    )

    return RunContext(
        run_id=run_id if run_id is not None else str(uuid.uuid4()),
        repo=repo,
        pr_number=pr_number,
        base_sha=base_sha,
        head_sha=head_sha,
    )


def fetch_changed_files(context: RunContext, *, client: Github | None = None) -> list[ChangedFile]:
    """Every file the pull request touched, as models rather than PyGithub objects.

    Narrowing here rather than downstream is what keeps the rest of stage 1 pure:
    :func:`~queryguard.pipeline.diff.build_sources` sees
    :class:`~queryguard.models.diff.ChangedFile` values, so it can be driven from
    a recorded payload without a client at all.
    """
    with _guard(f"listing files in {context.repo}#{context.pr_number}"):
        pull = _resolve(client).get_repo(context.repo).get_pull(context.pr_number)
        # PyGithub paginates this lazily; materializing it inside the guard means a
        # failure on page two is reported the same way as one on page one.
        return [
            ChangedFile(
                # `filename` is the head-side path — the new one for a rename, which
                # is the path a reviewer will be looking at and the only one a
                # finding may anchor to.
                path=changed.filename,
                status=ChangeStatus.parse(changed.status),
                previous_path=getattr(changed, "previous_filename", None),
                patch=changed.patch,
                additions=changed.additions,
                deletions=changed.deletions,
            )
            for changed in pull.get_files()
        ]


def read_head_file(context: RunContext, path: str, *, client: Github | None = None) -> str:
    """The text of ``path`` as it stands at the pull request's head commit.

    Pinned to ``head_sha`` rather than to the branch name: a branch moves, and a
    run that read half its files before a force-push and half after would produce
    a report describing a tree that never existed.
    """
    ref = context.head_sha
    if ref is None:
        msg = f"cannot read {path}: the run context carries no head SHA"
        raise GitHubUnavailable(msg)

    with _guard(f"reading {path} at {ref[:8]}"):
        contents = _resolve(client).get_repo(context.repo).get_contents(path, ref=ref)
        if isinstance(contents, list):
            # A directory. Nothing in a changed-files list should resolve to one,
            # so this is a bug or a path collision rather than a normal outcome.
            msg = f"{path} is a directory at {ref[:8]}, not a file"
            raise GitHubUnavailable(msg)
        return contents.decoded_content.decode("utf-8", errors="replace")


def fetch_diff(
    context: RunContext,
    *,
    client: Github | None = None,
    registry: ExtractorRegistry | None = None,
) -> list[SourceFile]:
    """Fetch the PR's diff as one source per changed file, ready for stage 2.

    Each source carries the head-side text in full and the hunks the pull request
    touched, so a finding's line number already refers to the head file rather
    than the base. :mod:`queryguard.pipeline.diff` explains why the content is the
    whole file and not the patch.

    Deleted files produce no source, and neither do files in a language no
    extractor claims. This returns the sources alone; a caller that also needs to
    know *which* files were skipped or unreadable wants
    :func:`queryguard.pipeline.ingest.ingest_pull_request`, which returns all
    three.
    """
    resolved = _resolve(client)
    return build_sources(
        context,
        fetch_changed_files(context, client=resolved),
        lambda path: read_head_file(context, path, client=resolved),
        registry=registry,
    ).sources


def upsert_report_comment(context: RunContext, report: Report) -> int:
    """Create or update QueryGuard's single comment on the PR.

    Searches the PR's comments for :data:`COMMENT_MARKER`; edits that comment if
    found, otherwise creates a new one. Returns the comment ID.
    """
    raise NotImplementedError("github.upsert_report_comment is not implemented yet")


class _guard:
    """Context manager translating anything GitHub raises into a safe exception.

    A class rather than ``@contextmanager``, and ``__exit__`` annotated
    ``Literal[False]`` rather than ``bool``: both forms of "may return True" tell
    a type checker the manager might *swallow* an exception, which makes every
    ``with _guard(...): return ...`` look like a function that can fall off its
    end. Saying it never suppresses is both the truth and what keeps the callers
    typeable.
    """

    def __init__(self, operation: str) -> None:
        self._operation = operation

    def __enter__(self) -> None:
        return None

    def __exit__(
        self, kind: object, value: BaseException | None, traceback: object
    ) -> Literal[False]:
        if value is None or isinstance(value, GitHubUnavailable):
            return False

        if isinstance(value, GithubException):
            detail = value.data.get("message") if isinstance(value.data, dict) else None
            suffix = f": {redact(str(detail))}" if detail else ""
            message = f"GitHub returned {value.status} while {self._operation}{suffix}"
        else:
            # Only the type name. An exception from a layer we do not control —
            # a socket error, a JSON decode, a library we have not audited — gets
            # no opportunity to put its own string in front of a user.
            message = f"{type(value).__name__} while {self._operation}"

        logger.error("github: %s", message, extra={"operation": self._operation})
        # `from None`: chaining would hang the original exception off ours, and a
        # traceback printer renders that chain. Suppressing it is the difference
        # between a message we vouch for and a message we merely prefixed.
        raise GitHubUnavailable(message) from None
