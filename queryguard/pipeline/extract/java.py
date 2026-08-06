"""Stage 2 (Java) — narrow Spring Data JPQL annotation extraction."""

from __future__ import annotations

import re

from queryguard.models.query import ExtractedQuery, Provenance, QueryKind

__all__ = ["extract_java"]


# This intentionally accepts only a single Java string literal or text block as the
# sole annotation argument. In particular, named arguments, concatenation, and
# ``nativeQuery = true`` do not match and remain work for later extraction stages.
QUERY_ANNOTATION = re.compile(
    r'''@Query\b\s*\(\s*(?:
        "(?P<string>(?:\\.|[^"\\\r\n])*)"\s*\)
        | """(?:\r\n|\n)(?P<text_block>.*?)"""\s*\)
    )''',
    re.DOTALL | re.VERBOSE,
)


def extract_java(path: str, content: str) -> list[ExtractedQuery]:
    """Extract JPQL from simple Spring Data ``@Query`` annotations.

    The source is searched rather than parsed: malformed Java and annotations outside
    this deliberately narrow shape simply produce no candidate. The JPQL itself is
    kept verbatim and is not parsed or normalized here.
    """
    queries: list[ExtractedQuery] = []

    for match in QUERY_ANNOTATION.finditer(content):
        text = match.group("string")
        start = match.start("string")
        if text is None:
            text = match.group("text_block")
            start = match.start("text_block")

        if text is None or start == -1:
            continue

        queries.append(
            ExtractedQuery(
                id=f"{path}:{len(queries) + 1}",
                kind=QueryKind.JPQL,
                text=text,
                provenance=Provenance(
                    file=path,
                    line=content.count("\n", 0, start) + 1,
                ),
            )
        )

    return queries
