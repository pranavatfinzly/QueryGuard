"""Stage 2 (SQL) — sqlglot-based extraction and normalization.

Handles ``.sql`` files, migrations, and SQL string literals. Queries that cannot
be parsed come back with ``parse_error`` set rather than guessed at — never regex
SQL.
"""

from __future__ import annotations

import sqlglot

from queryguard.models.query import ExtractedQuery, Provenance, QueryKind

__all__ = ["extract_from_sql"]


def extract_from_sql(
    path: str,
    content: str,
    dialect: str = "postgres",
    kind: QueryKind = QueryKind.RAW_SQL,
) -> list[ExtractedQuery]:
    """Extract statements from a ``.sql`` file or migration using sqlglot.

    Statement splitting is done by :func:`sqlglot.parse`, not by splitting on
    semicolons: a semicolon inside a string literal or a dollar-quoted function body
    is not a statement boundary, and only a parser knows the difference.

    Each statement's ``line`` is resolved from the sqlglot token position where
    available, so findings anchor to the statement rather than to the top of the
    file. A statement that fails to parse is still returned, with ``parse_error``
    set — the extract stage reports candidates, and the rule engine decides what is
    analyzable.
    """
    if not content.strip():
        return []

    try:
        statements = sqlglot.parse(content, read=dialect)
    except sqlglot.ParseError as error:
        # The whole file is unparseable, so there are no statement boundaries to
        # report against. Surface it as one unanalyzable candidate rather than
        # dropping the file silently.
        return [
            ExtractedQuery(
                id=f"{path}:1",
                kind=kind,
                text=content.strip(),
                dialect=dialect,
                provenance=Provenance(file=path, line=1),
                parse_error=str(error),
            )
        ]

    spans = _statement_spans(content, dialect)

    queries: list[ExtractedQuery] = []
    for index, statement in enumerate(statements):
        if statement is None:
            # sqlglot yields None for an empty segment, e.g. a trailing semicolon.
            continue

        # `text` is contractually the query *as written* (see models/query.py), so it
        # is sliced from the source rather than re-rendered from the AST. Rendering
        # would silently rewrite what the reviewer sees — `Customer c` becomes
        # `Customer AS c`, `:tier` becomes `%(tier)s` — and a report that quotes a
        # query the author never wrote is hard to trust.
        original, line = spans[index] if index < len(spans) else (None, None)

        queries.append(
            ExtractedQuery(
                id=f"{path}:{index + 1}",
                kind=kind,
                text=original if original is not None else statement.sql(dialect=dialect),
                normalized=statement.sql(dialect=dialect, normalize=True),
                dialect=dialect,
                provenance=Provenance(file=path, line=line),
            )
        )

    return queries


def _statement_spans(content: str, dialect: str) -> list[tuple[str, int]]:
    """Original text and starting line of each statement, split on semicolon tokens.

    Uses the tokenizer rather than ``content.split(";")`` for the same reason the
    parser splits statements: a semicolon inside a string literal or a dollar-quoted
    body is not a boundary.
    """
    try:
        tokens = sqlglot.tokenize(content, read=dialect)
    except sqlglot.TokenError:
        return []

    spans: list[tuple[str, int]] = []
    start_index: int | None = None
    start_line = 1

    for token in tokens:
        if token.token_type is sqlglot.TokenType.SEMICOLON:
            if start_index is not None:
                spans.append((content[start_index : token.start].strip(), start_line))
                start_index = None
            continue
        if start_index is None:
            start_index = token.start
            start_line = token.line

    if start_index is not None:
        spans.append((content[start_index:].strip(), start_line))

    return spans
