"""Command-line entry point for reviewing one GitHub pull request."""

from __future__ import annotations

import argparse
import logging
import re
import sys
import traceback
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from queryguard.models.report import Report, RunContext
from queryguard.pipeline.diff import INGEST_STAGE

if TYPE_CHECKING:
    from github import Github

    from queryguard.integrations.llm import LLMExplanationProvider
    from queryguard.models.diff import DiffIngest
    from queryguard.pipeline.extract.java_structure import ResolveJavaSource
    from queryguard.pipeline.runner import AnalysisRunner
    from queryguard.pipeline.static_rules.schema import SchemaProvider

logger = logging.getLogger(__name__)

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
        "--no-llm",
        action="store_true",
        help="skip LLM-authored explanations even when GROQ_API_KEY is configured; "
        "findings are still fully deterministic without it",
    )
    review.add_argument(
        "--debug",
        action="store_true",
        help="show an ImportError traceback for local diagnosis",
    )
    review.add_argument(
        "--fixture",
        type=Path,
        metavar="PATH",
        help="run --dry-run against an existing recorded PR fixture, without GitHub or Groq access",
    )
    return parser


def _load_effective_schema(
    context: RunContext,
    ingested: DiffIngest,
    client: Github,
) -> SchemaProvider:
    """The schema static rules should see for this run.

    Two independent paths, chosen by whether ``LIQUIBASE_CHANGELOG_PATH`` is
    configured — configuration precedence, not a fallback chain within either
    path:

    * **Explicit** (:func:`_load_explicit_schema`) — unchanged from before this
      module gained automatic discovery. A configured path is read from local
      disk and never silently second-guessed by discovery, however discovery
      might resolve the same repository; an operator who set the variable gets
      exactly what they configured.
    * **Discovered** (:func:`_load_discovered_schema`) — only reached when
      nothing is configured. QueryGuard looks for the repository's own
      ``db.liquibase.change-log`` declaration instead of requiring one.

    Explicit configuration always wins; see ``queryguard/db/discovery.py``'s
    module docstring for what discovery does and does not attempt.
    """
    from queryguard.config import get_settings

    changelog_path = get_settings().liquibase_changelog_path
    if changelog_path is not None:
        return _load_explicit_schema(context, ingested, client, changelog_path)
    return _load_discovered_schema(context, client)


def _load_explicit_schema(
    context: RunContext,
    ingested: DiffIngest,
    client: Github,
    changelog_path: str,
) -> SchemaProvider:
    """The schema for an explicitly configured ``LIQUIBASE_CHANGELOG_PATH``.

    Local-disk by default — the behaviour QueryGuard has always had. If the pull
    request's changed files touch the changelog tree that schema was built from,
    the schema is instead rebuilt from the *complete* changelog tree at the pull
    request's head commit, over the GitHub API, so a query added alongside a
    schema change in the same pull request is judged against the schema the pull
    request will actually produce rather than the one that predates it. See
    ``queryguard/db/liquibase.py``'s module docstring for why this is a full
    rebuild rather than a delta applied on top of the local-disk schema.
    """
    from queryguard.db.liquibase import (
        LiquibaseParseError,
        load_liquibase_schema_remote,
        load_schema_from_settings,
        resolve_pr_changelog_touch,
    )
    from queryguard.integrations.github import read_file_at_ref
    from queryguard.pipeline.static_rules.schema import StaticSchemaProvider

    schema = load_schema_from_settings(changelog_path)

    if not isinstance(schema, StaticSchemaProvider):
        # The local changelog could not be loaded at all — the same silent stub
        # QueryGuard has always fallen back to. There is nothing to rebuild from
        # a pull request in that case.
        return schema

    head_sha = context.head_sha
    if head_sha is None:
        return schema

    changed_paths = {
        *(source.path for source in ingested.sources),
        *(skipped.path for skipped in ingested.skipped),
        *(marker.removeprefix(f"{INGEST_STAGE}:") for marker in ingested.degraded_stages),
    }
    if not resolve_pr_changelog_touch(changelog_path, changed_paths):
        return schema

    try:
        return load_liquibase_schema_remote(
            changelog_path,
            lambda path: read_file_at_ref(context, path, ref=head_sha, client=client),
        )
    except LiquibaseParseError:
        logger.exception(
            "failed to rebuild the Liquibase schema from the pull request's head "
            "commit; falling back to the local-disk schema",
            extra={"run_id": context.run_id, "repo": context.repo, "pr_number": context.pr_number},
        )
        return schema


def _load_discovered_schema(context: RunContext, client: Github) -> SchemaProvider:
    """The schema QueryGuard finds on its own, with no configured changelog path.

    Sourced entirely over the GitHub API, pinned to the pull request's head
    commit — never local disk, because nothing guarantees a local checkout of
    an arbitrary ``OWNER/REPO`` corresponds to the repository being reviewed
    (see ``queryguard/db/discovery.py``'s module docstring). Discovery first
    locates ``db.liquibase.change-log`` in the repository's own configuration
    (a handful of small reads, never a repository-wide scan), then the
    *existing* remote Liquibase loader walks the changelog tree it names —
    exactly the loader :func:`_load_explicit_schema` already uses for a
    pull-request-head rebuild, reused rather than duplicated.

    Because this always reads at the pull request's head, there is no separate
    "did the pull request touch the changelog" gate the way
    :func:`_load_explicit_schema` has: a query-only pull request and a
    schema-changing one are both answered by the same one remote walk, and
    both correctly see the schema as it will actually be once the pull request
    merges.

    Every non-``DISCOVERED`` outcome — nothing found, more than one
    configuration file disagreeing, a discovered path that turns out not to
    resolve to a real changelog — degrades to
    :data:`~queryguard.pipeline.static_rules.schema.UNKNOWN_SCHEMA`, logged but
    never raised: an unconfigured, undiscoverable repository must analyze
    exactly as it did before this feature existed, not turn into a failed run.
    """
    from queryguard.db.discovery import DiscoveryStatus, discover_liquibase_changelog
    from queryguard.db.liquibase import LiquibaseParseError, build_table_schemas_remote
    from queryguard.integrations.github import read_file_at_ref
    from queryguard.pipeline.static_rules.schema import UNKNOWN_SCHEMA, StaticSchemaProvider

    log_context = {"run_id": context.run_id, "repo": context.repo, "pr_number": context.pr_number}

    head_sha = context.head_sha
    if head_sha is None:
        # No commit to pin reads to — nothing here could describe a tree that
        # actually exists.
        return UNKNOWN_SCHEMA

    def read(path: str) -> str:
        return read_file_at_ref(context, path, ref=head_sha, client=client)

    result = discover_liquibase_changelog(read)

    if result.status is DiscoveryStatus.NOT_FOUND:
        logger.debug(
            "no LIQUIBASE_CHANGELOG_PATH configured and no application "
            "configuration declared db.liquibase.change-log; continuing "
            "without a schema",
            extra=log_context,
        )
        return UNKNOWN_SCHEMA

    if result.status is DiscoveryStatus.AMBIGUOUS:
        logger.warning(
            "Liquibase changelog discovery is ambiguous: %s; set "
            "LIQUIBASE_CHANGELOG_PATH explicitly to resolve it",
            result.reason,
            extra=log_context,
        )
        return UNKNOWN_SCHEMA

    if result.status is DiscoveryStatus.INVALID:
        logger.warning(
            "Liquibase changelog discovery found an unusable configuration in %s: %s",
            result.source_file,
            result.reason,
            extra=log_context,
        )
        return UNKNOWN_SCHEMA

    if result.changelog_path is None:
        # Unreachable in practice — DISCOVERED always carries a path — but a
        # defensive fallback here costs nothing and keeps this function
        # correctly typed without asserting an invariant on another module's
        # behalf.
        return UNKNOWN_SCHEMA

    logger.info(
        "automatically discovered Liquibase changelog %s (from %s)",
        result.changelog_path,
        result.source_file,
        extra={**log_context, "changelog_path": result.changelog_path},
    )

    try:
        tables = build_table_schemas_remote(result.changelog_path, read)
    except LiquibaseParseError:
        logger.exception(
            "discovered changelog %s could not be loaded; continuing without a schema",
            result.changelog_path,
            extra=log_context,
        )
        return UNKNOWN_SCHEMA

    logger.info(
        "Liquibase schema loaded from discovered changelog: %d table(s)",
        len(tables),
        extra={**log_context, "number_of_tables": len(tables)},
    )
    return StaticSchemaProvider(tables)


def _java_source_resolver(context: RunContext, client: Github) -> ResolveJavaSource | None:
    """Read a Java file at the pull request's head, for cross-file resolution.

    An N+1 routinely spans files a pull request did not touch: the loop is edited,
    the repository interface it calls is not. Without a way to read that
    interface, its type resolves by naming convention alone and the finding is
    reported a tier weaker than the evidence deserves.

    Three properties make this safe to hand to the analyzer:

    * **Targeted.** The analyzer asks only for types actually used as receivers,
      by a path derived from the calling file's own package and imports. It never
      enumerates the repository.
    * **Cached, including misses.** A path that 404s is remembered as absent, so a
      type referenced from twenty call sites costs at most one request.
    * **Silent on failure.** GitHub being unavailable degrades resolution, not the
      run — the caller still gets every structural finding, just with the weaker
      tier. That is the same fail-soft contract every other optional input has.

    Returns None when the context carries no head SHA, since a read that cannot be
    pinned to a commit could describe a tree that never existed.
    """
    from queryguard.integrations.github import GitHubUnavailable, read_file_at_ref

    head_sha = context.head_sha
    if head_sha is None:
        return None

    cache: dict[str, str | None] = {}

    def resolve(path: str) -> str | None:
        if path not in cache:
            try:
                cache[path] = read_file_at_ref(context, path, ref=head_sha, client=client)
            except GitHubUnavailable:
                logger.debug(
                    "could not read %s at the head commit; falling back to "
                    "name-convention resolution",
                    path,
                    extra={"run_id": context.run_id, "source_path": path},
                )
                cache[path] = None
        return cache[path]

    return resolve


def review(
    repo: str,
    pr_number: int,
    *,
    post_comment: bool = False,
    dry_run: bool = False,
    client: Github | None = None,
    runner: AnalysisRunner | None = None,
    llm_provider: LLMExplanationProvider | None = None,
) -> Report:
    """Orchestrate the existing ingest, analysis, rendering, and comment stages.

    An injected client is the offline seam used by recorded fixtures. In a normal
    invocation, ``new_client`` obtains and validates GitHub configuration.

    ``llm_provider`` defaults to ``None``: this function reads no LLM-related
    configuration on its own, so calling it directly — as the whole test suite
    does — costs nothing and touches no network beyond GitHub's. ``main`` is the
    one caller that constructs a provider from process configuration (respecting
    ``--no-llm``) and passes it in; a caller embedding :func:`review` that wants
    the same behavior can do the same with
    :func:`queryguard.integrations.groq.create_default_llm_provider`. Ignored
    when ``runner`` is supplied directly, the same way ``runner`` already
    supersedes the schema this function would otherwise load.

    A :class:`~queryguard.integrations.github.GitHubUnavailable` from ingestion —
    GitHub could not be reached, or refused a request, before a single file was
    read — degrades rather than raises (CLAUDE.md invariant 5): the caller still
    gets a :class:`Report`, naming the failure, with no queries and no findings
    rather than either an exception or a comment that could read as "nothing
    wrong here". Nothing else is caught this broadly. A programming error —
    ``TypeError``, ``AssertionError``, any bug in extraction or the rule engine —
    is not GitHub being unavailable, and must still reach the caller: silently
    degrading those would hide a real QueryGuard failure behind a green check,
    which is a worse outcome than a loud one.
    """
    from queryguard.integrations.github import GitHubUnavailable, new_client, upsert_report_comment
    from queryguard.pipeline.ingest import ingest_pull_request
    from queryguard.pipeline.runner import AnalysisRunner
    from queryguard.pipeline.static_rules import RuleEngine

    resolved_client = client if client is not None else new_client()

    try:
        ingested = ingest_pull_request(repo, pr_number, client=resolved_client)
    except GitHubUnavailable as error:
        # The comment's target is `repo`/`pr_number` alone — already known from
        # the caller's own arguments, not from anything `ingest_pull_request`
        # would have resolved. A degraded comment can still be attempted below
        # even though ingestion itself never got that far.
        context = RunContext(run_id=str(uuid.uuid4()), repo=repo, pr_number=pr_number)
        report = Report(context=context, degraded_stages=[f"{INGEST_STAGE}:{error}"])
    else:
        context = ingested.context
        if runner is not None:
            resolved_runner = runner
        else:
            schema = _load_effective_schema(context, ingested, resolved_client)
            resolved_runner = AnalysisRunner(
                engine=RuleEngine(schema=schema), llm_provider=llm_provider
            )
        report = resolved_runner.run(
            repo=context.repo,
            pr_number=context.pr_number,
            sources=ingested.sources,
            context=context,
            initial_degraded_stages=ingested.degraded_stages,
            resolve_source=_java_source_resolver(context, resolved_client),
        )

    if post_comment and not dry_run:
        # The integration owns the idempotent create-or-update behavior.
        try:
            upsert_report_comment(context, report, client=resolved_client)
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

        # Fixture mode is the offline, no-credentials path (see --fixture's help
        # text); Groq is real network the same way GitHub would be, so it stays
        # off there regardless of --no-llm. Everywhere else, GROQ_API_KEY's
        # presence is the switch — --no-llm is the explicit override for someone
        # who has a key configured but wants a purely deterministic run anyway.
        llm_provider = None
        if not args.no_llm and args.fixture is None:
            from queryguard.integrations.groq import create_default_llm_provider

            llm_provider = create_default_llm_provider()

        report = review(
            args.repo,
            args.pr,
            post_comment=args.post_comment,
            dry_run=args.dry_run,
            client=client,
            llm_provider=llm_provider,
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
