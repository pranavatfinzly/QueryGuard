"""Stage 2 — Extract.

Pulls query candidates out of a PR diff and records their provenance so findings
can be anchored back to the diff. Dispatches per changed file:

- ``.sql`` files, migrations, and SQL string literals -> :mod:`.sql`
- Java sources -> :mod:`.java`, which delegates method names to :mod:`.derived`
"""

from __future__ import annotations

from queryguard.models.query import ExtractedQuery
from queryguard.pipeline.extract.derived import parse_derived_method
from queryguard.pipeline.extract.java import extract_from_java
from queryguard.pipeline.extract.sql import extract_from_sql

__all__ = [
    "extract_from_java",
    "extract_from_sql",
    "extract_queries",
    "parse_derived_method",
]


def extract_queries(diff: str) -> list[ExtractedQuery]:
    """Extract every query candidate from a unified diff.

    Dispatches per changed file to :func:`extract_from_sql` or
    :func:`extract_from_java` based on path and extension.
    """
    raise NotImplementedError("extract.extract_queries is not implemented yet")
