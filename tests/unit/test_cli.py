"""CLI orchestration tests, driven entirely by the recorded GitHub fixture."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from github.GithubException import GithubException

from queryguard import cli
from queryguard.config import MissingConfiguration, override_settings
from queryguard.fixtures import load_recorded_fixture
from queryguard.integrations import github
from queryguard.models.report import Report, RunContext
from tests.conftest import RecordedGitHub, RecordedPullRequest

RECORDED_FIXTURE = Path("tests/fixtures/diffs")


def test_review_parser_accepts_owner_repository_and_positive_pr() -> None:
    args = cli.build_parser().parse_args(["review", "--repo", "acme/billing", "--pr", "42"])

    assert args.repo == "acme/billing"
    assert args.pr == 42


def test_normal_review_requires_github_token() -> None:
    with override_settings(), pytest.raises(MissingConfiguration, match="GITHUB_TOKEN"):
        cli.review("acme/billing", 1)


@pytest.mark.parametrize("number", ["0", "-1", "not-a-number"])
def test_review_parser_rejects_invalid_pr_numbers(number: str) -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.build_parser().parse_args(["review", "--repo", "acme/billing", "--pr", number])


@pytest.mark.parametrize("repo", ["acme", "acme/", "/billing", "acme/billing/extra", "acme billing"])
def test_review_parser_rejects_invalid_repository_format(repo: str) -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.build_parser().parse_args(["review", "--repo", repo, "--pr", "42"])


def test_review_runs_recorded_fixture_without_network_and_preserves_ingest_context(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    fake = recorded_github
    pull = recorded_pr
    report = cli.review(pull.repo, pull.number, client=fake.client, dry_run=True)

    assert report.context.base_sha == pull.base_sha
    assert report.context.head_sha == pull.head_sha
    assert report.findings
    assert fake.comments == []


def test_main_prints_rendered_markdown(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    report = Report(context=RunContext(run_id="r", repo="acme/billing", pr_number=1))
    monkeypatch.setattr(cli, "review", lambda *args, **kwargs: report)

    assert cli.main(["review", "--repo", "acme/billing", "--pr", "1"]) == 0
    assert capsys.readouterr().out == "<!-- queryguard:report -->\n\n## QueryGuard\n\nNo queries were found in this change.\n"


def test_post_comment_creates_then_updates_one_comment(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    fake = recorded_github
    pull = recorded_pr

    cli.review(pull.repo, pull.number, client=fake.client, post_comment=True)
    cli.review(pull.repo, pull.number, client=fake.client, post_comment=True)

    assert len(fake.comments) == 1


def test_dry_run_never_writes_even_when_post_comment_is_requested(
    recorded_github: RecordedGitHub, recorded_pr: RecordedPullRequest
) -> None:
    fake = recorded_github
    pull = recorded_pr

    cli.review(pull.repo, pull.number, client=fake.client, post_comment=True, dry_run=True)

    assert fake.comments == []


def test_offline_fixture_dry_run_needs_no_token_network_or_writes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unexpected_client() -> None:
        raise AssertionError("fixture mode must not create a network client")

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(github, "new_client", unexpected_client)
    recorded, client = load_recorded_fixture(RECORDED_FIXTURE)

    assert (
        cli.main(
            [
                "review",
                "--repo",
                recorded.repo,
                "--pr",
                str(recorded.number),
                "--dry-run",
                "--fixture",
                str(RECORDED_FIXTURE),
            ]
        )
        == 0
    )
    rendered = capsys.readouterr().out
    assert rendered.startswith("<!-- queryguard:report -->\n\n## QueryGuard\n")
    assert "Reviewed 20 queries and found 15 problems." in rendered
    # The fixture client intentionally has no comment API at all.
    assert not hasattr(client.get_repo(recorded.repo).get_pull(recorded.number), "create_issue_comment")


def test_fixture_mode_refuses_comment_posting() -> None:
    recorded, _ = load_recorded_fixture(RECORDED_FIXTURE)

    with pytest.raises(SystemExit, match="2"):
        cli.main(
            [
                "review",
                "--repo",
                recorded.repo,
                "--pr",
                str(recorded.number),
                "--dry-run",
                "--fixture",
                str(RECORDED_FIXTURE),
                "--post-comment",
            ]
        )


def test_comment_failure_is_fail_soft_and_the_report_is_still_printed(
    recorded_github: RecordedGitHub,
    recorded_pr: RecordedPullRequest,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = recorded_github
    pull = recorded_pr
    fake.raise_on_comment = GithubException(403, {"message": "Forbidden"}, None)
    monkeypatch.setattr(github, "new_client", lambda: fake.client)

    assert cli.main(["review", "--repo", pull.repo, "--pr", str(pull.number), "--post-comment"]) == 0
    assert "Not fully analyzed" in capsys.readouterr().out


def test_github_failure_is_safe_and_never_prints_a_token(
    recorded_github: RecordedGitHub,
    recorded_pr: RecordedPullRequest,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = recorded_github
    pull = recorded_pr
    token = "ghp_" + "Z" * 36
    fake.raise_on_pull = GithubException(401, {"message": f"Bad credentials {token}"}, None)
    monkeypatch.setattr(github, "new_client", lambda: fake.client)

    assert cli.main(["review", "--repo", pull.repo, "--pr", str(pull.number)]) == 1
    output = capsys.readouterr()
    assert token not in output.out
    assert token not in output.err
    assert "<redacted>" in output.err


def test_unrecoverable_configuration_error_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "review", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret")))

    assert cli.main(["review", "--repo", "acme/billing", "--pr", "1"]) == 1
    assert "secret" not in capsys.readouterr().err


def test_debug_reports_an_import_error_traceback_without_changing_normal_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = ImportError("cannot import name 'MissingThing' from 'queryguard.example'")
    monkeypatch.setattr(cli, "review", lambda *args, **kwargs: (_ for _ in ()).throw(missing))

    assert cli.main(["review", "--repo", "acme/billing", "--pr", "1"]) == 1
    assert "MissingThing" not in capsys.readouterr().err

    assert cli.main(["review", "--repo", "acme/billing", "--pr", "1", "--debug"]) == 1
    assert "cannot import name 'MissingThing'" in capsys.readouterr().err


def test_cli_only_orchestrates_existing_pipeline_components() -> None:
    tree = ast.parse(Path("queryguard/cli.py").read_text(encoding="utf-8"))
    definitions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

    assert not {"fetch_pull_request", "fetch_diff", "ingest", "render_markdown", "upsert_report_comment"} & definitions
