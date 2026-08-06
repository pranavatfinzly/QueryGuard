"""Stage 8 — Report rendering.

Merges static findings, plan findings, index suggestions, and N+1 findings into a
single ranked Markdown report: severity, evidence (plan excerpts, cost deltas),
and a suggested fix per finding.

Rendering is deliberately a pure function of the :class:`Report` model — the
comment body is user-facing, so it is snapshot-tested, and that only works if the
same report always renders the same Markdown. Nothing here reads a clock, a
counter, or the environment, and the run ID is deliberately absent from the body:
the comment is rewritten in place on every run, so a body that changed when the
findings had not would show a reviewer a diff that means nothing.

Posting the comment belongs to :mod:`queryguard.integrations.github`.

The layout puts coverage gaps *above* the findings. A report over a partially
read change that leads with its findings reads as a complete review, and a
reviewer who trusts it stops looking — which is the failure mode the fail-soft
design exists to prevent (CLAUDE.md invariant 5). Caveats are sections, not
footnotes.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence

from queryguard.integrations.github import COMMENT_MARKER
from queryguard.models.finding import Evidence, Finding, Severity, Suggestion
from queryguard.models.query import ExtractedQuery
from queryguard.models.report import Report

__all__ = ["rank_findings", "render_markdown"]

#: Severity sections, worst first. Iterated in this order rather than sorted, so a
#: severity added to the enum without a decision about where it belongs shows up
#: here as a missing section rather than silently sorting itself somewhere.
_SEVERITY_DISPLAY: tuple[tuple[Severity, str, str], ...] = (
    (Severity.CRITICAL, "🔴", "Critical"),
    (Severity.HIGH, "🟠", "High"),
    (Severity.MEDIUM, "🟡", "Medium"),
    (Severity.LOW, "🔵", "Low"),
    (Severity.INFO, "⚪", "Info"),
)

#: Fence language for quoted query text. JPQL and derived-method renderings are not
#: SQL, but GitHub has no lexer for them and `sql` highlights them acceptably; the
#: kind is stated in prose beside the block rather than implied by the fence.
_FENCE_LANGUAGE = "sql"

_BACKTICK_RUN = re.compile(r"`+")
_WHITESPACE = re.compile(r"\s+")


def rank_findings(findings: list[Finding]) -> list[Finding]:
    """Order findings for presentation, most important first."""
    raise NotImplementedError("report.rank_findings is not implemented yet")


def render_markdown(report: Report) -> str:
    """Render a report as the Markdown body of the PR comment.

    The body carries :data:`queryguard.integrations.github.COMMENT_MARKER` as its
    first line so re-runs edit the existing comment instead of adding another.

    Pure: the same report always renders byte-identical Markdown.
    """
    queries = _queries_by_id(report.queries)
    unanalyzable = [query for query in report.queries if query.parse_error is not None]

    blocks: list[str] = [COMMENT_MARKER, "## QueryGuard", _summary(report, unanalyzable)]
    blocks.extend(_degraded_section(report.degraded_stages))
    blocks.extend(_unanalyzable_section(unanalyzable))
    blocks.extend(_findings_sections(report.findings, queries))

    return "\n\n".join(blocks) + "\n"


def _summary(report: Report, unanalyzable: Sequence[ExtractedQuery]) -> str:
    """One line saying what was reviewed and what came of it.

    Reports the number of queries actually analyzed, not the number extracted —
    an unanalyzable candidate was read but not reviewed, and counting it would
    overstate the coverage this report represents.
    """
    analyzed = len(report.queries) - len(unanalyzable)

    if not report.queries:
        found = "No queries were found in this change."
    elif analyzed == 0:
        # Queries were found and none could be read. "Found no problems" would be
        # a clean bill of health for a review that never happened.
        found = (
            f"Found {_count(len(report.queries), 'query', 'queries')}, "
            f"none of which could be reviewed."
        )
    elif not report.findings:
        found = f"Reviewed {_count(analyzed, 'query', 'queries')} and found no problems."
    else:
        found = (
            f"Reviewed {_count(analyzed, 'query', 'queries')} and found "
            f"{_count(len(report.findings), 'problem', 'problems')}."
        )

    if report.degraded_stages or unanalyzable:
        return f"{found} **Part of this change could not be reviewed — see below.**"
    return found


def _degraded_section(degraded_stages: Sequence[str]) -> list[str]:
    """The stages that failed soft, as a section a reviewer cannot skim past."""
    if not degraded_stages:
        return []

    return [
        "### ⚠️ Not fully analyzed",
        (
            "These stages failed and were skipped, so this report covers less than "
            "the change does. Everything below is still accurate — it is just not "
            "everything."
        ),
        "\n".join(f"- {_degraded_item(stage)}" for stage in degraded_stages),
    ]


def _degraded_item(marker: str) -> str:
    """Render one ``degraded_stages`` marker.

    Markers are either a bare stage name or ``<stage>:<detail>`` — the runner
    qualifies extraction per source, because losing one file out of ten is a
    materially different report from losing all ten. Split generically rather than
    matching known stage names, so a stage added later renders without an edit
    here.
    """
    stage, separator, detail = marker.partition(":")
    if separator and detail:
        return f"**{stage}** — `{detail}`"
    return f"**{marker}**"


def _unanalyzable_section(unanalyzable: Sequence[ExtractedQuery]) -> list[str]:
    """Queries that were found but could not be parsed.

    Named rather than omitted: a query QueryGuard could not read is not a query
    with no problems, and the difference is the whole point of reporting it.
    """
    if not unanalyzable:
        return []

    return [
        "### ⚠️ Queries that could not be parsed",
        ("These were found in the change but could not be read, so no rule ran against them."),
        "\n".join(f"- {_anchor(query)} — {_one_line(query.parse_error)}" for query in unanalyzable),
    ]


def _findings_sections(
    findings: Sequence[Finding], queries: dict[str, ExtractedQuery]
) -> list[str]:
    """One section per severity present, worst first."""
    blocks: list[str] = []

    for severity, badge, label in _SEVERITY_DISPLAY:
        # Filtered in the order the findings arrived, so the engine's ranking
        # within a severity survives into the report.
        at_severity = [finding for finding in findings if finding.severity is severity]
        if not at_severity:
            continue

        blocks.append(f"### {badge} {label}")
        for finding in at_severity:
            blocks.extend(_finding_blocks(finding, queries))

    return blocks


def _finding_blocks(finding: Finding, queries: dict[str, ExtractedQuery]) -> list[str]:
    """One finding: what, where, the query itself, why it matters, and the fix."""
    blocks = [f"#### {finding.title}", f"**Where:** {_finding_anchor(finding, queries)}"]

    query = queries.get(finding.query_id) if finding.query_id is not None else None
    if query is not None:
        blocks.append(_code_block(query.text))

    blocks.append(finding.explanation)
    blocks.append(f"**Impact:** {finding.impact}")

    blocks.extend(_evidence_blocks(finding.evidence))
    blocks.extend(_suggestion_blocks(finding.suggestions))

    if finding.confidence is not None:
        # CLAUDE.md: a claim that could not be checked against a plan or an AST is
        # labelled rather than presented as established.
        blocks.append(
            f"*Confidence: {finding.confidence:.0%} — this finding was inferred and "
            f"could not be verified automatically.*"
        )

    blocks.append(f"<sub>`{finding.rule_id}`</sub>")
    return blocks


def _finding_anchor(finding: Finding, queries: dict[str, ExtractedQuery]) -> str:
    """Where a finding points, including the other queries a cross-query one spans."""
    anchor = _provenance_anchor(
        finding.provenance.file, finding.provenance.line, finding.provenance.symbol
    )

    related = [query_id for query_id in finding.query_ids if query_id != finding.query_id]
    if not related:
        return anchor

    # An N+1 spans a set of queries; naming only the first would hide what the
    # finding is actually about.
    others = ", ".join(f"`{_anchor_for_id(query_id, queries)}`" for query_id in related)
    return f"{anchor}, with {others}"


def _anchor_for_id(query_id: str, queries: dict[str, ExtractedQuery]) -> str:
    """A related query's location, falling back to its ID when it is not in scope."""
    query = queries.get(query_id)
    if query is None:
        return query_id
    return _location(query.provenance.file, query.provenance.line)


def _anchor(query: ExtractedQuery) -> str:
    """A query's ``file:line``, code-spanned."""
    return _provenance_anchor(query.provenance.file, query.provenance.line, query.provenance.symbol)


def _provenance_anchor(file: str, line: int | None, symbol: str | None) -> str:
    """``file:line``, with the enclosing symbol when the source named one.

    Every part is optional except the file, and an absent part is left out rather
    than rendered — a comment reading `Repo.java:None` is worse than one reading
    `Repo.java`.
    """
    anchor = f"`{_location(file, line)}`"
    if symbol is not None:
        return f"{anchor} (`{symbol}`)"
    return anchor


def _location(file: str, line: int | None) -> str:
    """``file:line``, or just the file when no line was resolved."""
    return f"{file}:{line}" if line is not None else file


def _evidence_blocks(evidence: Sequence[Evidence]) -> list[str]:
    """Supporting detail — a plan excerpt, a cost delta, a snippet."""
    if not evidence:
        return []

    return [
        "<details><summary>Evidence</summary>\n\n"
        + "\n".join(f"- **{item.label}:** {item.detail}" for item in evidence)
        + "\n\n</details>"
    ]


def _suggestion_blocks(suggestions: Sequence[Suggestion]) -> list[str]:
    """Every proposed fix, with its measured impact where one exists."""
    blocks: list[str] = []

    for suggestion in suggestions:
        blocks.append(f"**Suggested fix:** {suggestion.description}")
        if suggestion.sql is not None:
            blocks.append(_code_block(suggestion.sql))
        impact = _cost_delta(suggestion.cost_before, suggestion.cost_after)
        if impact is not None:
            blocks.append(impact)

    return blocks


def _cost_delta(before: float | None, after: float | None) -> str | None:
    """The simulated cost change, when both ends were measured.

    Both or neither: a "before" with no "after" is not a measurement, and printing
    half of one invites the reader to supply the other half themselves.
    """
    if before is None or after is None:
        return None

    line = f"**Simulated cost:** {before:,.2f} → {after:,.2f}"
    if before <= 0:
        return line

    # Rounded away from flattering the suggestion, never toward it. A 99.96%
    # reduction printed as "100% lower" reads as "this becomes free", which is a
    # claim about a *simulated* plan that nobody measured. Floor the improvement,
    # ceil the regression, so the number is never better than the truth.
    change = (before - after) / before
    if change >= 0:
        return f"{line} ({math.floor(change * 100)}% lower)"
    return f"{line} ({math.ceil(-change * 100)}% higher)"


def _code_block(text: str) -> str:
    """Fence ``text``, choosing a fence the content cannot break out of."""
    return f"{_fence(text)}{_FENCE_LANGUAGE}\n{text.strip()}\n{_fence(text)}"


def _fence(text: str) -> str:
    """A backtick fence longer than any backtick run inside ``text``.

    A quoted query containing a fenced block of its own — a query built in a
    Markdown-formatted string, say — would otherwise close the block early and
    spill the rest of the report into the page as prose.
    """
    longest = max((len(run) for run in _BACKTICK_RUN.findall(text)), default=0)
    return "`" * max(3, longest + 1)


def _one_line(text: str | None) -> str:
    """Collapse a message to one line so it can sit inside a list item."""
    if text is None:
        return "could not be parsed"
    collapsed = _WHITESPACE.sub(" ", text).strip()
    return collapsed if collapsed else "could not be parsed"


def _queries_by_id(queries: Iterable[ExtractedQuery]) -> dict[str, ExtractedQuery]:
    """Index queries by ID for finding-to-query lookup.

    First occurrence wins. IDs are unique within a file but not within a run — the
    same path submitted twice yields the same IDs (STATUS.md, TD-3) — so this is
    the point that would need a run-qualified ID. Until then the duplicate is a
    byte-identical copy of the same source, so which one is quoted does not change
    the rendered output.
    """
    index: dict[str, ExtractedQuery] = {}
    for query in queries:
        index.setdefault(query.id, query)
    return index


def _count(number: int, singular: str, plural: str) -> str:
    """``"1 query"`` / ``"3 queries"``."""
    return f"{number} {singular if number == 1 else plural}"
