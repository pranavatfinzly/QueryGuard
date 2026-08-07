"""Command-line entry point for reviewing one GitHub pull request."""

from __future__ import annotations

import argparse
import re
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from github import Github

    from queryguard.models.report import Report
    from queryguard.pipeline.runner import AnalysisRunner

_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")


def _repository(value: str) -> str:
    """Accept precisely GitHub's owner/repository form at the CLI boundary."""
    if not _REPOSITORY.fullmatch(value):
        raise argparse.ArgumentTypeError("--repo must use OWNER/REPO format")
    return value


def _pr_number(value: str) -> int:
    """Parse a positive pull-request number without accepting zero or negatives."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--pr must be a positive integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("--pr must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    """Build the small public command surface."""
    parser = argparse.ArgumentParser(prog="queryguard")
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review", help="review a pull request")
    review.add_argument("--repo", required=True, type=_repository, metavar="OWNER/REPO")
    review.add_argument("--pr", required=True, type=_pr_number, metavar="NUMBER")
    review.add_argument("--post-comment", action="store_true")
    review.add_argument("--dry-run", action="store_true")
    review.add_argument(
        "--debug",
        action="store_true",
        help="show an ImportError traceback for local diagnosis",
    )
    review.add_argument(
        "--fixture",
        type=Path,
        metavar="PATH",
        help="run --dry-run against an existing recorded PR fixture, without GitHub access",
    )
    return parser


def review(
    repo: str,
    pr_number: int,
    *,
    post_comment: bool = False,
    dry_run: bool = False,
    client: Github | None = None,
    runner: AnalysisRunner | None = None,
) -> Report:
    """Orchestrate the existing ingest, analysis, rendering, and comment stages.

    An injected client is the offline seam used by recorded fixtures. In a normal
    invocation, ``new_client`` obtains and validates GitHub configuration.
    """
    from queryguard.integrations.github import GitHubUnavailable, new_client, upsert_report_comment
    from queryguard.pipeline.ingest import ingest_pull_request
    from queryguard.pipeline.runner import AnalysisRunner

    resolved_client = client if client is not None else new_client()
    ingested = ingest_pull_request(repo, pr_number, client=resolved_client)
    resolved_runner = runner if runner is not None else AnalysisRunner()
    report = resolved_runner.run(
        repo=ingested.context.repo,
        pr_number=ingested.context.pr_number,
        sources=ingested.sources,
        context=ingested.context,
        initial_degraded_stages=ingested.degraded_stages,
    )

    if post_comment and not dry_run:
        # The integration owns the idempotent create-or-update behavior.
        try:
            upsert_report_comment(ingested.context, report, client=resolved_client)
        except GitHubUnavailable:
            # Posting is optional: retain the useful static report and make the
            # coverage gap visible, matching the runner's fail-soft contract.
            report = report.model_copy(
                update={"degraded_stages": [*report.degraded_stages, "post_comment"]}
            )

    return report


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command, returning an exit status instead of leaking tracebacks."""
    args = build_parser().parse_args(argv)
    if args.command != "review":  # pragma: no cover - argparse enforces this today.
        return 2
    if args.fixture is not None and not args.dry_run:
        build_parser().error("--fixture requires --dry-run")
    if args.fixture is not None and args.post_comment:
        build_parser().error("--fixture cannot be used with --post-comment")

    try:
        client = None
        if args.fixture is not None:
            from queryguard.fixtures import FixtureError, load_recorded_fixture

            recorded, client = load_recorded_fixture(args.fixture)
            if (args.repo, args.pr) != (recorded.repo, recorded.number):
                raise FixtureError(
                    "--repo and --pr must match the repository and pull request recorded by --fixture"
                )
        report = review(
            args.repo,
            args.pr,
            post_comment=args.post_comment,
            dry_run=args.dry_run,
            client=client,
        )
        # Rendering is deliberately here, after every optional operation, so stdout
        # is always exactly the final report body and never a credential or log.
        from queryguard.pipeline.report import render_markdown

        _print_markdown(render_markdown(report))
        return 0
    except Exception as error:
        # GitHub's integration already provides safe, actionable messages. For
        # every other boundary (including configuration import), avoid rendering an
        # arbitrary third-party exception string that could contain a credential.
        # Do not import these classes here: a missing token can be raised while
        # importing ``config`` itself, before the module finished loading.
        safe_error_types = {
            ("queryguard.config", "MissingConfiguration"),
            ("queryguard.fixtures", "FixtureError"),
            ("queryguard.integrations.github", "GitHubUnavailable"),
        }
        if (type(error).__module__, type(error).__name__) in safe_error_types:
            print(f"QueryGuard failed: {error}", file=sys.stderr)
        else:
            print(f"QueryGuard failed: {type(error).__name__}", file=sys.stderr)
            if args.debug and isinstance(error, ImportError):
                # ImportError messages name modules/symbols, not credentials. Keep
                # debug deliberately narrow so an arbitrary third-party exception
                # never receives an opportunity to render secret-bearing context.
                traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)
        return 1


def _print_markdown(markdown: str) -> None:
    """Write Markdown even when a Windows console uses a legacy code page."""
    try:
        sys.stdout.write(markdown)
    except UnicodeEncodeError:
        # Report sections use severity emoji. GitHub Actions is UTF-8, but an
        # installed command can also be piped from a Windows terminal configured
        # with cp1252. Bytes preserve the report rather than turning a successful
        # offline review into a spurious CLI failure.
        sys.stdout.buffer.write(markdown.encode("utf-8"))
        sys.stdout.buffer.flush()


def entrypoint() -> None:
    """Console-script wrapper required by ``project.scripts``."""
    raise SystemExit(main())
