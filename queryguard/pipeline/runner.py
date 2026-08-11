"""Pipeline orchestration — drives the stages that are implemented.

This is not a stage. Every module beside it owns one step of the run and knows
nothing about the others; something has to put them in order, and if that lived in
the FastAPI route then the CLI and the eventual webhook handler would each grow
their own copy of it. So the ordering, the fail-soft boundaries, and the run's log
record live here, and the API layer is left with request parsing and response
shaping.

Wired today, in run order:

1. **Extract** — :func:`queryguard.pipeline.extract.extract_source` per source.
2. **Static analysis** — :class:`~queryguard.pipeline.static_rules.RuleEngine` over
   everything extract produced.
3. **N+1 detection** — :func:`~queryguard.pipeline.nplusone.detect_n_plus_one` over
   the *sources*, not just the queries. It is the one stage that needs the files
   themselves: a repository call inside a loop is a fact about control flow, and
   control flow is exactly what an ``ExtractedQuery`` does not carry. Its findings
   merge into the same list as the static ones, so ranking orders them together.
4. **Rank + cap** — :func:`~queryguard.pipeline.report.rank_findings` deduplicates
   and orders the merged findings; :func:`~queryguard.pipeline.report.cap_findings`
   bounds how many reach the comment. Stage 8 in CLAUDE.md's numbering, done here
   rather than only in the renderer because a capped-but-unlabelled report would
   otherwise report a false total in ``AnalyzeResponse`` as well as in Markdown.

Stages 4–6 (provision, EXPLAIN, HypoPG) are not wired because they are not
implemented. The runner does not pretend otherwise: it returns the
:class:`~queryguard.models.report.Report` those stages would have enriched,
carrying only what the static and structural paths could establish.

Fail-soft is the point of the structure (CLAUDE.md invariant 5). A source that
cannot be extracted loses that source and nothing else; a rule engine that raises
loses the static findings and still returns the queries. Either way the caller gets
a report naming what degraded, never an exception.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING

from queryguard.integrations.llm import LLMExplanationProvider
from queryguard.integrations.p6spy import StatementGroup
from queryguard.models.finding import Finding
from queryguard.models.query import ExtractedQuery, SourceFile
from queryguard.models.report import Report, RunContext
from queryguard.pipeline.extract import extract_source
from queryguard.pipeline.extract.java_structure import ResolveJavaSource
from queryguard.pipeline.report import DEFAULT_MAX_FINDINGS, cap_findings, rank_findings
from queryguard.pipeline.static_rules import RuleEngine

if TYPE_CHECKING:
    from github import Github

__all__ = ["EXTRACT_STAGE", "NPLUS_ONE_STAGE", "STATIC_RULES_STAGE", "AnalysisRunner"]

logger = logging.getLogger(__name__)

#: Name recorded in ``Report.degraded_stages`` when the static stage itself fails.
STATIC_RULES_STAGE = "static_rules"

#: Recorded when N+1 detection fails. A bare stage name rather than a per-file
#: marker: the stage reasons across the whole source set at once, so there is no
#: single file whose loss it could name honestly.
NPLUS_ONE_STAGE = "nplusone"

#: Extraction degrades per source, as ``extract:<path>``, rather than as a bare
#: stage name: losing one file out of ten is a materially different report from
#: losing all ten, and a single ``"extract"`` marker cannot say which happened.
EXTRACT_STAGE = "extract"


class AnalysisRunner:
    """Runs the implemented pipeline over a set of SQL sources.

    Holds no per-run state, and must not grow any: the ``/analyze`` route is a plain
    ``def``, so FastAPI runs it in a threadpool and one shared instance serves
    concurrent requests. A run's identity and results live in the
    :class:`~queryguard.models.report.Report` built per call, never on ``self``.

    The rule engine is injected rather than constructed inline so a caller can supply
    a narrower rule set or a real schema provider without reaching into this module.

    ``llm_provider`` is injected the same way, and for the same reason: this class
    must stay constructible with no configuration at all, so every existing caller
    — including the whole test suite — keeps producing the purely deterministic
    report it always has. It defaults to ``None`` rather than reading process
    configuration itself; a caller that wants Groq (or any other
    :class:`~queryguard.integrations.llm.LLMExplanationProvider`) wired in by
    default constructs one from settings and passes it explicitly — see
    :func:`queryguard.integrations.groq.create_default_llm_provider`, used by
    :mod:`queryguard.cli`.
    """

    def __init__(
        self,
        engine: RuleEngine | None = None,
        *,
        llm_provider: LLMExplanationProvider | None = None,
    ) -> None:
        # Constructed eagerly, not per run: RuleEngine reads the live rule registry
        # through a property, so a shared instance still sees rules registered after
        # it was built.
        self._engine = engine if engine is not None else RuleEngine()
        self._llm_provider = llm_provider

    def run(
        self,
        *,
        repo: str,
        pr_number: int,
        sources: Sequence[SourceFile],
        run_id: str | None = None,
        context: RunContext | None = None,
        initial_degraded_stages: Sequence[str] = (),
        post_comment: bool = False,
        client: Github | None = None,
        max_findings: int = DEFAULT_MAX_FINDINGS,
        repeated_statements: Sequence[StatementGroup] | None = None,
        resolve_source: ResolveJavaSource | None = None,
    ) -> Report:
        """Extract queries from ``sources``, apply the static rules, and report.

        ``run_id`` is generated unless supplied; callers pass one when the identifier
        comes from elsewhere (a webhook delivery ID, a test fixture). ``max_findings``
        bounds the comment's length; findings beyond it are still found and ranked,
        just not shown — see :func:`~queryguard.pipeline.report.cap_findings`.

        ``repeated_statements`` and ``resolve_source`` are both optional inputs to
        the N+1 stage: a captured p6spy log to corroborate a structural pattern
        against, and a way to read a repository interface the pull request did not
        change. Omitting either narrows what that stage can conclude — never what
        the other stages do.
        """
        started = time.perf_counter()
        context = (
            context
            if context is not None
            else RunContext(
                run_id=run_id if run_id is not None else str(uuid.uuid4()),
                repo=repo,
                pr_number=pr_number,
            )
        )

        queries, extract_degraded = self._extract(context, sources)
        findings, static_degraded = self._apply_static_rules(context, queries)
        cross_query, nplusone_degraded = self._detect_n_plus_one(
            context,
            sources,
            queries,
            repeated_statements=repeated_statements,
            resolve_source=resolve_source,
        )
        findings = [*findings, *cross_query]
        degraded_stages = [
            *initial_degraded_stages,
            *extract_degraded,
            *static_degraded,
            *nplusone_degraded,
        ]

        findings = rank_findings(findings)
        findings, omitted_findings = cap_findings(findings, max_findings=max_findings)

        comment_id = None
        if post_comment:
            from queryguard.integrations.github import GitHubUnavailable, upsert_report_comment

            temp_report = Report(
                context=context,
                queries=queries,
                findings=findings,
                degraded_stages=degraded_stages,
                omitted_findings=omitted_findings,
            )
            try:
                comment_id = upsert_report_comment(context, temp_report, client=client)
            except GitHubUnavailable:
                degraded_stages.append("post_comment")

        elapsed_ms = (time.perf_counter() - started) * 1000
        # The message carries the same fields as `extra` because the two are read by
        # different tools: `extra` by whatever ships structured logs, the message by
        # whoever is tailing them. Neither should have to reconstruct the other.
        logger.info(
            "analysis complete: run_id=%s number_of_queries=%d number_of_findings=%d "
            "number_of_findings_omitted=%d processing_time_ms=%.3f degraded=%d",
            context.run_id,
            len(queries),
            len(findings),
            omitted_findings,
            elapsed_ms,
            len(degraded_stages),
            extra={
                "run_id": context.run_id,
                "repo": context.repo,
                "pr_number": context.pr_number,
                "number_of_queries": len(queries),
                "number_of_findings": len(findings),
                "number_of_findings_omitted": omitted_findings,
                "processing_time_ms": elapsed_ms,
                "degraded_stages": degraded_stages,
            },
        )

        return Report(
            context=context,
            queries=queries,
            findings=findings,
            degraded_stages=degraded_stages,
            comment_id=comment_id,
            omitted_findings=omitted_findings,
        )

    def _extract(
        self, context: RunContext, sources: Sequence[SourceFile]
    ) -> tuple[list[ExtractedQuery], list[str]]:
        """Stage 2, one source at a time so a bad source costs only itself.

        A source degrades in two ways, and both produce the same marker because they
        are the same caveat to whoever reads the report — *this file was not fully
        analyzed*. Either the extractor returned a candidate it could not parse, or
        it raised outright.
        """
        queries: list[ExtractedQuery] = []
        degraded: list[str] = []

        for source in sources:
            # Built once so the two ways a source degrades cannot drift into two
            # spellings of the same marker.
            marker = f"{EXTRACT_STAGE}:{source.path}"
            try:
                # The whole model, not `(path, content)`: a source may carry
                # options its extractor needs — `SqlSource.dialect` is one — and
                # unpacking it here would silently drop them.
                extracted = extract_source(source)
            except Exception:
                # Stage boundary. The extractor already turns malformed SQL into an
                # unanalyzable candidate, so reaching here means something genuinely
                # unexpected — which is exactly what must not take the run down.
                logger.exception(
                    "extract failed for %s; continuing with the remaining sources",
                    source.path,
                    extra={"run_id": context.run_id, "source_path": source.path},
                )
                degraded.append(marker)
                continue

            queries.extend(extracted)

            # Counted rather than collected: the candidates themselves are already in
            # `queries`, and a second list of the same objects earns nothing.
            unparseable = sum(1 for query in extracted if query.parse_error is not None)
            if unparseable:
                logger.warning(
                    "extract: %d candidate(s) in %s could not be parsed",
                    unparseable,
                    source.path,
                    extra={"run_id": context.run_id, "source_path": source.path},
                )
                degraded.append(marker)

        return queries, degraded

    def _apply_static_rules(
        self, context: RunContext, queries: list[ExtractedQuery]
    ) -> tuple[list[Finding], list[str]]:
        """Stage 3, in one call so each query is parsed once and ranked against all.

        One call rather than one per source: the engine parses each query exactly
        once, and a single call is also what lets it rank a CRITICAL finding from the
        last file above a MEDIUM one from the first.

        The engine already confines a failing *rule* to that rule. This boundary
        catches what it cannot: a failure in its own parse-and-dispatch loop, which
        would otherwise discard the extract stage's work along with the findings.
        """
        try:
            return self._engine.analyze(queries), []
        except Exception:
            logger.exception(
                "static rule stage failed; reporting without static findings",
                extra={"run_id": context.run_id, "number_of_queries": len(queries)},
            )
            return [], [STATIC_RULES_STAGE]

    def _detect_n_plus_one(
        self,
        context: RunContext,
        sources: Sequence[SourceFile],
        queries: list[ExtractedQuery],
        *,
        repeated_statements: Sequence[StatementGroup] | None,
        resolve_source: ResolveJavaSource | None,
    ) -> tuple[list[Finding], list[str]]:
        """Stage 7, over the sources rather than the extracted queries.

        The only stage handed the raw sources. It has to be: the loop that makes a
        query repeat is not in the query, and nothing between here and the file
        text carries control flow.

        Fail-soft at the stage boundary, like the rule engine above it. Structural
        analysis reads whatever a pull request contains — including Java that is
        mid-edit, generated, or written against a language version this analyzer
        does not fully model — so a malformed file must cost this stage's findings
        and nothing else. A crashed N+1 stage still leaves every static finding
        intact, which is CLAUDE.md's invariant 5 applied at the one place a new
        stage could most easily break it.
        """
        try:
            # Imported here rather than at module scope: the stage pulls in sqlglot
            # and the structural analyzer, and a runner constructed for a SQL-only
            # run should not pay for them.
            from queryguard.pipeline.nplusone import detect_n_plus_one

            return (
                detect_n_plus_one(
                    sources,
                    queries=queries,
                    repeated_statements=repeated_statements,
                    resolve_source=resolve_source,
                    explain=self._llm_provider,
                ),
                [],
            )
        except Exception:
            logger.exception(
                "n+1 stage failed; reporting without cross-query findings",
                extra={"run_id": context.run_id, "number_of_sources": len(sources)},
            )
            return [], [NPLUS_ONE_STAGE]
