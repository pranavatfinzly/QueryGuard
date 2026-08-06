"""Stage 2 (Java) — Spring Data ``@Query`` annotations and derived method names.

Recognition is still pattern-based; the JavaParser sidecar CLAUDE.md specifies is
the eventual replacement and would slot in behind
:class:`~queryguard.pipeline.extract.base.Extractor` without any other module
noticing. What has changed is *what the patterns are applied to*: every match
here runs against :class:`~queryguard.pipeline.extract.java_source.JavaSource`,
which has already separated code from comments and literals. Patterns therefore
cannot match a query that only exists in a comment, and region extents come from
real bracket matching rather than from the first ``}`` in the file.

Both halves of the file are collected and then emitted in source order, so the
queries in a report follow the file a reviewer is reading.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from queryguard.models.query import ExtractedQuery, Provenance, QueryKind, SourceFile
from queryguard.pipeline.extract.base import query_id, symbol_query_id
from queryguard.pipeline.extract.derived import (
    entity_table,
    parse_derived_query,
    render_derived_query,
)
from queryguard.pipeline.extract.java_source import JavaSource

__all__ = ["JavaExtractor", "extract_java"]


class JavaExtractor:
    """The registered :class:`~queryguard.pipeline.extract.base.Extractor` for Java.

    Java extraction takes no per-source options today, so this is a pure adapter.
    It exists anyway rather than registering :func:`extract_java` directly,
    because the registry's contract is one interface for every language — and
    when the JavaParser sidecar lands, the sidecar handle and its timeout are
    exactly the state that will live here.
    """

    def extract(self, source: SourceFile) -> list[ExtractedQuery]:
        return extract_java(source.path, source.content)


# This intentionally accepts only one Java string literal or text block. Named forms
# require exactly ``value`` and ``nativeQuery`` arguments, in either order. In
# particular, concatenation and every other annotation argument remain future work.
QUERY_ANNOTATION = re.compile(
    r'''@Query\b\s*\(\s*(?:
        nativeQuery\s*=\s*(?P<native_first>true|false)\s*,\s*
        value\s*=\s*(?:
            "(?P<native_first_string>(?:\\.|[^"\\\r\n])*)"
            | """(?:\r\n|\n)(?P<native_first_text_block>.*?)"""
        )
        | value\s*=\s*(?:
            "(?P<native_last_string>(?:\\.|[^"\\\r\n])*)"
            | """(?:\r\n|\n)(?P<native_last_text_block>.*?)"""
        )\s*,\s*nativeQuery\s*=\s*(?P<native_last>true|false)
        | "(?P<jpql_string>(?:\\.|[^"\\\r\n])*)"
        | """(?:\r\n|\n)(?P<jpql_text_block>.*?)"""
    )\s*\)''',
    re.DOTALL | re.VERBOSE,
)

#: Any ``@Query`` at all, including the shapes :data:`QUERY_ANNOTATION` declines.
#: Used only to suppress derived-method decoding: an annotated method's SQL comes
#: from the annotation whether or not this extractor can read it yet, so decoding
#: its *name* would invent a query the application never issues.
ANY_QUERY_ANNOTATION = re.compile(r"@Query\b\s*\(")

REPOSITORY_INTERFACE = re.compile(
    r"\binterface\s+(?P<repository>[A-Za-z][A-Za-z0-9]*Repository)\b[^{}]*\{"
)
DERIVED_METHOD_DECLARATION = re.compile(
    r"(?m)^[^\n;{}]*\b(?P<method>(?:find|count|exists|delete)By[A-Za-z0-9_]+)\s*\([^;{}]*\)\s*;"
)

#: Value groups of :data:`QUERY_ANNOTATION`, in the order they are tried. Exactly
#: one can match, so the first that is not None is the query text. A table rather
#: than a chain of ``if text is None`` fallthroughs: the alternation has six arms
#: today and grows with every annotation shape supported, and the fallthrough form
#: made adding one a six-line edit in the middle of the logic.
_VALUE_GROUPS = (
    "jpql_string",
    "jpql_text_block",
    "native_first_string",
    "native_first_text_block",
    "native_last_string",
    "native_last_text_block",
)

#: Groups holding the ``nativeQuery`` flag, whichever argument order was used.
_NATIVE_FLAG_GROUPS = ("native_first", "native_last")


@dataclass(frozen=True)
class _Candidate:
    """One query found in the file, before it is given an identity.

    Carries ``offset`` so annotations and derived methods can be merged into one
    source-ordered sequence, and ``symbol`` so each gets the identity that suits
    it: a derived method *is* its name, while an annotation has only a position.
    """

    offset: int
    line: int
    kind: QueryKind
    text: str
    symbol: str | None = None


def extract_java(path: str, content: str) -> list[ExtractedQuery]:
    """Extract ``@Query`` annotations and supported derived methods from Java.

    Query text is kept verbatim and is not parsed or normalized here — that is
    the rule engine's job, and JPQL is not SQL. Anything outside the supported
    shapes produces no candidate rather than a guess.
    """
    source = JavaSource.of(content)
    annotated = _annotation_extents(source)

    candidates = [
        *_annotation_candidates(source),
        *_derived_candidates(source, annotated),
    ]
    candidates.sort(key=lambda candidate: candidate.offset)

    return [
        ExtractedQuery(
            id=(
                symbol_query_id(path, candidate.symbol)
                if candidate.symbol is not None
                else query_id(path, ordinal)
            ),
            kind=candidate.kind,
            text=candidate.text,
            provenance=Provenance(file=path, line=candidate.line, symbol=candidate.symbol),
        )
        for ordinal, candidate in enumerate(candidates, start=1)
    ]


def _annotation_candidates(source: JavaSource) -> list[_Candidate]:
    """Every ``@Query`` this extractor can read, as candidates."""
    candidates: list[_Candidate] = []

    for match in QUERY_ANNOTATION.finditer(source.code):
        if not source.is_code(match.start()):
            # The annotation is inside a string literal — Java source quoted
            # within Java source, in a test fixture or a code-generation
            # template. Comments cannot reach here at all: they are already
            # blanked out of `source.code`.
            continue

        value = _annotation_value(match)
        if value is None:
            continue
        text, start = value

        candidates.append(
            _Candidate(
                offset=match.start(),
                # The value's line, not the annotation's: for a text block the
                # query starts on the line after `@Query("""`, and that is the
                # line a reviewer looking for the SQL will find it on.
                line=source.line_at(start),
                kind=QueryKind.SQL if _is_native(match) else QueryKind.JPQL,
                text=text,
            )
        )

    return candidates


def _annotation_value(match: re.Match[str]) -> tuple[str, int] | None:
    """The query text and its offset, from whichever value group matched."""
    for group in _VALUE_GROUPS:
        text = match.group(group)
        if text is not None:
            return text, match.start(group)
    return None


def _is_native(match: re.Match[str]) -> bool:
    """Whether the annotation declared ``nativeQuery = true``."""
    return any(match.group(group) == "true" for group in _NATIVE_FLAG_GROUPS)


def _derived_candidates(source: JavaSource, annotated: list[tuple[int, int]]) -> list[_Candidate]:
    """Supported derived methods declared in repository interfaces."""
    candidates: list[_Candidate] = []

    for interface in REPOSITORY_INTERFACE.finditer(source.code):
        extent = _interface_body(source, interface)
        if extent is None:
            continue
        body_start, body_end = extent

        table = entity_table(interface.group("repository"))

        # Sliced rather than searched with `pos`/`endpos`: with those, `^` does not
        # match at `pos`, so the first declaration of a single-line interface —
        # `interface R { Customer findById(Long id); }` — would never be seen.
        body = source.code[body_start:body_end]
        for method in DERIVED_METHOD_DECLARATION.finditer(body):
            start = body_start + method.start()
            if _is_annotated(start, annotated, source):
                continue

            derived = parse_derived_query(method.group("method"))
            if derived is None:
                continue

            candidates.append(
                _Candidate(
                    offset=start,
                    line=source.line_at(start),
                    kind=QueryKind.SPRING_DATA_DERIVED,
                    text=render_derived_query(derived, table),
                    symbol=method.group("method"),
                )
            )

    return candidates


def _interface_body(source: JavaSource, interface: re.Match[str]) -> tuple[int, int] | None:
    """Offsets bounding an interface's body, or None if its braces do not balance.

    The opening brace is the last character the interface pattern matched. Its
    partner comes from real bracket matching, because ``find("}")`` returns the
    first closing brace in the file — which for any repository carrying a
    ``default`` method is that method's, leaving every declaration after it
    outside the "body" and silently unextracted.
    """
    open_brace = interface.end() - 1
    close_brace = source.matching_bracket(open_brace)
    if close_brace is None:
        return None
    return open_brace + 1, close_brace


def _annotation_extents(source: JavaSource) -> list[tuple[int, int]]:
    """Start and end offset of every ``@Query`` annotation, in source order.

    Computed once for the file. The previous form re-scanned the whole prefix
    with the full annotation pattern for each derived method, which is quadratic
    in a large repository interface — exactly the file this extractor is aimed at.
    """
    extents: list[tuple[int, int]] = []

    for match in ANY_QUERY_ANNOTATION.finditer(source.code):
        if not source.is_code(match.start()):
            continue
        close = source.matching_bracket(match.end() - 1)
        if close is None:
            # Unbalanced parentheses: the annotation has no knowable extent, so
            # it cannot be said to decorate anything. Recording a guessed one
            # would suppress methods it may not cover.
            continue
        extents.append((match.start(), close + 1))

    return extents


def _is_annotated(method_start: int, annotated: list[tuple[int, int]], source: JavaSource) -> bool:
    """Whether a ``@Query`` annotation directly decorates this declaration.

    Only the nearest preceding annotation can, so this is a binary search rather
    than a scan: if the closest one does not reach the declaration, none does.
    """
    index = bisect.bisect_right(annotated, (method_start, method_start)) - 1
    if index < 0:
        return False

    _, end = annotated[index]
    return end <= method_start and source.is_blank_between(end, method_start)
