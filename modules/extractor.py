"""Stage 2 — Extract.

Pulls query candidates out of a PR diff and records their provenance.

- Raw SQL files, migrations, and SQL string literals: parsed with ``sqlglot``.
- Java sources: ``@Query`` annotations, ``createQuery`` / ``createNativeQuery``
  calls, and Spring Data repository method names, via the JavaParser sidecar.

Queries that cannot be parsed are returned with ``parse_error`` set rather than
guessed at — never regex SQL.
"""

from __future__ import annotations

from modules.models import ExtractedQuery

__all__ = ["extract_queries", "extract_from_sql", "extract_from_java"]


def extract_queries(diff: str) -> list[ExtractedQuery]:
    """Extract every query candidate from a unified diff.

    Dispatches per changed file to :func:`extract_from_sql` or
    :func:`extract_from_java` based on path and extension.
    """
    raise NotImplementedError("extractor.extract_queries is not implemented yet")


def extract_from_sql(path: str, content: str) -> list[ExtractedQuery]:
    """Extract statements from a ``.sql`` file or migration using sqlglot."""
    raise NotImplementedError("extractor.extract_from_sql is not implemented yet")


def extract_from_java(path: str, content: str) -> list[ExtractedQuery]:
    """Extract JPQL/HQL, native queries, and derived methods from a Java source.

    Delegates parsing to the JavaParser sidecar, which emits JSON; all analysis
    stays on the Python side.
    """
    raise NotImplementedError("extractor.extract_from_java is not implemented yet")
