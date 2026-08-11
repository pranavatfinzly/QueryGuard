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
3. **Rank + cap** — :func:`~queryguard.pipeline.report.rank_findings` deduplicates
   and orders the merged findings; :func:`~queryguard.pipeline.report.cap_findings`
   bounds how many reach the comment. Stage 8 in CLAUDE.md's numbering, done here
   rather than only in the renderer because a capped-but-unlabelled report would
   otherwise report a false total in ``AnalyzeResponse`` as well as in Markdown.

Stages 4–7 (provision, EXPLAIN, HypoPG, N+1) are not wired because they are not
implemented. The runner does not pretend otherwise: it returns the
:class:`~queryguard.models.report.Report` those stages would have enriched,
carrying only what the static path could establish.

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

from queryguard.models.finding import Finding
from queryguard.models.query import ExtractedQuery, SourceFile
from queryguard.models.report import Report, RunContext
from queryguard.pipeline.extract import extract_source
from queryguard.pipeline.report import DEFAULT_MAX_FINDINGS, cap_findings, rank_findings
from queryguard.pipeline.static_rules import RuleEngine

if TYPE_CHECKING:
    from github import Github

__all__ = ["EXTRACT_STAGE", "STATIC_RULES_STAGE", "AnalysisRunner"]

logger = logging.getLogger(__name__)

#: Name recorded in ``Report.degraded_stages`` when the static stage itself fails.
STATIC_RULES_STAGE = "static_rules"

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
    """

    def __init__(self, engine: RuleEngine | None = None) -> None:
        # Constructed eagerly, not per run: RuleEngine reads the live rule registry
        # through a property, so a shared instance still sees rules registered after
        # it was built.
        self._engine = engine if engine is not None else RuleEngine()

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
    ) -> Report:
        """Extract queries from ``sources``, apply the static rules, and report.

        ``run_id`` is generated unless supplied; callers pass one when the identifier
        comes from elsewhere (a webhook delivery ID, a test fixture). ``max_findings``
        bounds the comment's length; findings beyond it are still found and ranked,
        just not shown — see :func:`~queryguard.pipeline.report.cap_findings`.
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
        degraded_stages = [*initial_degraded_stages, *extract_degraded, *static_degraded]

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
