"""Stage 2 (SQL) — sqlglot-based extraction and normalization.

Handles ``.sql`` files, migrations, and SQL string literals. Queries that cannot
be parsed come back with ``parse_error`` set rather than guessed at — never regex
SQL.
"""

from __future__ import annotations

from queryguard.models.query import ExtractedQuery

__all__ = ["extract_from_sql"]


def extract_from_sql(path: str, content: str) -> list[ExtractedQuery]:
    """Extract statements from a ``.sql`` file or migration using sqlglot."""
    raise NotImplementedError("extract.sql.extract_from_sql is not implemented yet")
