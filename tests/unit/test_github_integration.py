"""The GitHub integration and the ingest stage it feeds.

Driven entirely by ``tests/fixtures/diffs/`` through the PyGithub stand-in in
``conftest.py``: no network, no credentials, no ``monkeypatch`` of module state.

Half of this file is about the token. That is proportionate — this is the only
module in QueryGuard that handles a credential, so it is the only place one can
escape from, and "no token is ever logged" is a claim that has to be checked
rather than intended.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from github.GithubException import GithubException, RateLimitExceededException

from queryguard.config import MissingConfiguration, override_settings
from queryguard.integrations import github
from queryguard.integrations.github import GitHubUnavailable, redact
from queryguard.models.diff import ChangeStatus, SkipReason
from queryguard.models.report import RunContext
from queryguard.pipeline.extract import ExtractorRegistry, SqlExtractor
from queryguard.pipeline.ingest import ingest_pull_request
from queryguard.pipeline.runner import AnalysisRunner
from tests.conftest import RecordedGitHub, RecordedPullRequest

REPOSITORY = Path(__file__).resolve().parents[2]
PACKAGE = REPOSITORY / "queryguard"

#: Shaped like a real classic personal access token so the redactor has to earn
#: its pass. Not a real credential: 40 characters of 'A' after the prefix.
TOKEN = "ghp_" + "A" * 36

ORDER_REPOSITORY = "repository/OrderRepository.java"
DELETED_ENUM = "domain/OrderStatus.java"
README = "queryguard-sandbox/README.md"


# --- Resolving the pull request ------------------------------------------------


def test_fetch_pull_request_records_both_shas(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    context = github.fetch_pull_request(
        recorded_pr.repo, recorded_pr.number, client=recorded_github.client
    )

    assert context.repo == recorded_pr.repo
    assert context.pr_number == recorded_pr.number
    assert context.base_sha == recorded_pr.base_sha
    assert context.head_sha == recorded_pr.head_sha


def test_a_run_id_is_generated_unless_one_is_supplied(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    generated = github.fetch_pull_request(
        recorded_pr.repo, recorded_pr.number, client=recorded_github.client
    )
    supplied = github.fetch_pull_request(
        recorded_pr.repo, recorded_pr.number, run_id="delivery-7", client=recorded_github.client
    )

    assert generated.run_id
    assert supplied.run_id == "delivery-7"


def test_changed_files_are_narrowed_to_models_not_pygithub_objects(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    context = github.fetch_pull_request(
        recorded_pr.repo, recorded_pr.number, client=recorded_github.client
    )

    files = github.fetch_changed_files(context, client=recorded_github.client)
    renamed = next(f for f in files if f.status is ChangeStatus.RENAMED)

    assert len(files) == len(recorded_pr.entries)
    assert renamed.previous_path is not None
    assert renamed.previous_path != renamed.path
    assert renamed.previous_path.endswith("OrderItemRepository.java")
    assert renamed.path.endswith("OrderLineRepository.java")


def test_head_reads_are_pinned_to_the_head_sha(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    # Not to the branch name. A branch moves, and a run that read half its files
    # before a force-push and half after would describe a tree that never existed.
    context = github.fetch_pull_request(
        recorded_pr.repo, recorded_pr.number, client=recorded_github.client
    )

    github.fetch_diff(context, client=recorded_github.client)

    assert recorded_github.head_reads
    assert {ref for _, ref in recorded_github.head_reads} == {recorded_pr.head_sha}


def test_reading_head_without_a_head_sha_is_refused(recorded_github: RecordedGitHub) -> None:
    # Falling back to the default branch here would analyze a different tree and
    # report line numbers against a file the pull request never contained.
    context = RunContext(run_id="r", repo="acme/x", pr_number=1)

    with pytest.raises(GitHubUnavailable, match="no head SHA"):
        github.read_head_file(context, "a.sql", client=recorded_github.client)


def test_fetch_diff_returns_one_source_per_analyzable_file(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    context = github.fetch_pull_request(
        recorded_pr.repo, recorded_pr.number, client=recorded_github.client
    )

    sources = github.fetch_diff(context, client=recorded_github.client)
    paths = [source.path for source in sources]

    assert len(sources) == 4
    assert recorded_pr.path(DELETED_ENUM) not in paths
    assert recorded_pr.path(README) not in paths
    assert all(source.hunks for source in sources)


def test_fetch_diff_honours_an_injected_language_set(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    sql_only = ExtractorRegistry()
    sql_only.register(".sql", SqlExtractor())
    context = github.fetch_pull_request(
        recorded_pr.repo, recorded_pr.number, client=recorded_github.client
    )

    sources = github.fetch_diff(context, client=recorded_github.client, registry=sql_only)

    assert [source.path.rsplit("/", 1)[-1] for source in sources] == [
        "V1__create_tables.sql",
        "V2__reporting_indexes.sql",
    ]


# --- The ingest stage ----------------------------------------------------------


def test_ingest_returns_the_context_and_every_account_of_the_diff(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    result = ingest_pull_request(
        recorded_pr.repo, recorded_pr.number, run_id="run-1", client=recorded_github.client
    )

    assert result.context.run_id == "run-1"
    assert result.context.head_sha == recorded_pr.head_sha
    assert len(result.sources) == 4
    assert {skip.reason for skip in result.skipped} == {
        SkipReason.DELETED,
        SkipReason.UNSUPPORTED_LANGUAGE,
    }
    assert result.degraded_stages == []


def test_one_run_resolves_the_repository_through_one_client(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    # The client is built once in ingest and threaded through every call. Without
    # that, each of the seven requests in this run would authenticate separately.
    ingest_pull_request(recorded_pr.repo, recorded_pr.number, client=recorded_github.client)

    assert set(recorded_github.repo_lookups) == {recorded_pr.repo}


def test_a_file_that_raises_during_ingest_degrades_that_file_only(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    recorded_github.fail_head_for = {recorded_pr.path(ORDER_REPOSITORY)}

    result = ingest_pull_request(
        recorded_pr.repo, recorded_pr.number, client=recorded_github.client
    )

    assert result.degraded_stages == [f"ingest:{recorded_pr.path(ORDER_REPOSITORY)}"]
    assert len(result.sources) == 3


def test_ingest_output_drives_the_rest_of_the_pipeline(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    # The end the milestone is aimed at: a real recorded pull request goes diff ->
    # extract -> rules and produces findings anchored to head-file lines.
    result = ingest_pull_request(
        recorded_pr.repo, recorded_pr.number, run_id="run-1", client=recorded_github.client
    )

    report = AnalysisRunner().run(
        repo=result.context.repo,
        pr_number=result.context.pr_number,
        sources=result.sources,
        run_id=result.context.run_id,
    )

    assert report.findings
    by_path = {source.path: source for source in result.sources}
    for finding in report.findings:
        source = by_path[finding.provenance.file]
        assert finding.provenance.line is not None
        # Every anchor lands inside the head file it names — the property that
        # makes a line number in the PR comment clickable rather than misleading.
        assert 1 <= finding.provenance.line <= len(source.content.split("\n"))


def test_the_deleted_file_never_reaches_the_rule_engine(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    result = ingest_pull_request(
        recorded_pr.repo, recorded_pr.number, client=recorded_github.client
    )
    report = AnalysisRunner().run(
        repo=result.context.repo, pr_number=result.context.pr_number, sources=result.sources
    )

    assert recorded_pr.path(DELETED_ENUM) not in {q.provenance.file for q in report.queries}


# --- Failures cross the boundary as one type -----------------------------------


def test_a_github_error_becomes_one_exception_type_carrying_the_status(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    recorded_github.raise_on_pull = GithubException(404, {"message": "Not Found"}, None)

    with pytest.raises(GitHubUnavailable) as raised:
        github.fetch_pull_request(
            recorded_pr.repo, recorded_pr.number, client=recorded_github.client
        )

    assert "404" in str(raised.value)
    assert "Not Found" in str(raised.value)
    assert f"{recorded_pr.repo}#{recorded_pr.number}" in str(raised.value)


def test_a_non_github_failure_carries_only_its_type_name(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    # An exception from a layer we do not control gets no opportunity to put its
    # own string in front of a user — which is also why it cannot leak one.
    recorded_github.raise_on_files = TimeoutError("connect to 10.0.0.1 timed out")
    context = github.fetch_pull_request(
        recorded_pr.repo, recorded_pr.number, client=recorded_github.client
    )

    with pytest.raises(GitHubUnavailable) as raised:
        github.fetch_changed_files(context, client=recorded_github.client)

    assert "TimeoutError" in str(raised.value)
    assert "10.0.0.1" not in str(raised.value)


def test_the_original_exception_is_not_chained_onto_ours(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    # Chaining would hang the original off ours, and a traceback printer renders
    # the chain — undoing every guarantee about what the message contains.
    recorded_github.raise_on_pull = GithubException(401, {"message": f"token {TOKEN}"}, None)

    with pytest.raises(GitHubUnavailable) as raised:
        github.fetch_pull_request(
            recorded_pr.repo, recorded_pr.number, client=recorded_github.client
        )

    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__


def test_a_rate_limit_is_reported_as_the_status_it_is(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    recorded_github.raise_on_pull = RateLimitExceededException(
        403, {"message": "API rate limit exceeded"}, None
    )

    with pytest.raises(GitHubUnavailable, match="403"):
        github.fetch_pull_request(
            recorded_pr.repo, recorded_pr.number, client=recorded_github.client
        )


def test_our_own_exception_is_not_wrapped_twice(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    # read_head_file raises GitHubUnavailable itself for a missing head SHA. If the
    # guard re-wrapped it, the message would accumulate a prefix per layer.
    context = RunContext(run_id="r", repo=recorded_pr.repo, pr_number=recorded_pr.number)

    with pytest.raises(GitHubUnavailable) as raised:
        github.read_head_file(context, "a.sql", client=recorded_github.client)

    assert str(raised.value).count("GitHub returned") == 0


# --- The token ------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_" + "A" * 36,
        "gho_" + "B" * 36,
        "ghu_" + "C" * 36,
        "ghs_" + "D" * 36,
        "ghr_" + "E" * 36,
        "github_pat_" + "F" * 22 + "_" + "G" * 59,
    ],
    ids=["classic-pat", "oauth", "user-to-server", "server-to-server", "refresh", "fine-grained"],
)
def test_every_credential_shape_github_issues_is_redacted(secret: str) -> None:
    redacted = redact(f"Bad credentials: {secret} rejected")

    assert secret not in redacted
    assert github.REDACTED in redacted


def test_redaction_does_not_eat_ordinary_text() -> None:
    # A redactor that fires on prose gets disabled by the first person it confuses.
    text = "GitHub returned 404 while reading acme/billing#12: Not Found"

    assert redact(text) == text


def test_a_token_inside_githubs_own_error_message_never_reaches_the_caller(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    # The realistic leak: GitHub echoes something containing a credential, and we
    # forward its message verbatim.
    recorded_github.raise_on_pull = GithubException(
        401, {"message": f"Bad credentials for {TOKEN}"}, None
    )

    with pytest.raises(GitHubUnavailable) as raised:
        github.fetch_pull_request(
            recorded_pr.repo, recorded_pr.number, client=recorded_github.client
        )

    assert TOKEN not in str(raised.value)
    assert github.REDACTED in str(raised.value)


def test_a_token_in_an_unfamiliar_exception_never_reaches_the_caller(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    recorded_github.raise_on_pull = ValueError(f"invalid header Authorization: Bearer {TOKEN}")

    with pytest.raises(GitHubUnavailable) as raised:
        github.fetch_pull_request(
            recorded_pr.repo, recorded_pr.number, client=recorded_github.client
        )

    assert TOKEN not in str(raised.value)
    assert "Authorization" not in str(raised.value)


def test_no_log_record_from_a_failing_run_carries_the_token(
    recorded_github: RecordedGitHub,
    recorded_pr: RecordedPullRequest,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # End to end, and through the noisiest path there is: the head read fails with
    # a token-bearing error, ingest catches it at the stage boundary and calls
    # logger.exception, which renders a traceback. Nothing in it may be the token.
    recorded_github.raise_on_contents = GithubException(
        401, {"message": f"Bad credentials {TOKEN}"}, None
    )

    with caplog.at_level(logging.DEBUG), override_settings(github_token=TOKEN) as settings:
        result = ingest_pull_request(
            recorded_pr.repo, recorded_pr.number, client=recorded_github.client
        )

        assert TOKEN not in repr(settings)

    assert len(result.degraded_stages) == 4
    for record in caplog.records:
        assert TOKEN not in record.getMessage()
        assert TOKEN not in str(record.exc_info)
        assert TOKEN not in str(record.__dict__)


def test_a_call_without_an_injected_client_cannot_silently_reach_the_network() -> None:
    # What makes "unit tests run from the recorded fixture with no network calls" a
    # property rather than a habit. A test that forgets to inject the stand-in does
    # not quietly open a socket against a real repository: building a client needs a
    # token, the suite has none, and the run fails here instead.
    with pytest.raises(MissingConfiguration, match="GITHUB_TOKEN"):
        github.fetch_pull_request("acme/billing", 1)


def test_the_token_is_read_in_exactly_one_place(recorded_pr: RecordedPullRequest) -> None:
    # The structural half of the guarantee: a value that is only ever read once,
    # in a function that hands it straight to Auth.Token, cannot be interpolated
    # into a log line somewhere else. Asserted against the source tree so a second
    # reader added later fails here rather than in an incident.
    del recorded_pr

    readers = [
        path.relative_to(REPOSITORY).as_posix()
        for path in PACKAGE.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "require_github_token"
    ]

    assert readers == ["queryguard/integrations/github.py"]


def test_the_module_never_interpolates_the_token_into_a_string() -> None:
    # `new_client` is the only function that holds the value. Anything it does
    # beyond passing it to Auth.Token — an f-string, a log call, a URL — would
    # show up as the token flowing somewhere else, so pin its whole body.
    source = (PACKAGE / "integrations" / "github.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    new_client = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "new_client"
    )

    calls = [
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(new_client)
        if isinstance(node, ast.Call)
    ]

    assert sorted(calls) == ["Github", "Token", "get_settings", "require_github_token"]
    assert not [node for node in ast.walk(new_client) if isinstance(node, ast.JoinedStr)]
