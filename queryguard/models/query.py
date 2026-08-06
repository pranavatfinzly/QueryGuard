"""Query contracts — what the extract stage produces.

See :mod:`queryguard.models` for why these live in models rather than beside the
stage that builds them.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from queryguard.models.base import Contract


class QueryKind(str, Enum):
    """Where a query came from, which decides how it is parsed and bound."""

    RAW_SQL = "raw_sql"
    SQL = "sql"
    JPQL = "jpql"
    HQL = "hql"
    JPA_NATIVE = "jpa_native"
    SPRING_DATA_DERIVED = "spring_data_derived"


class SourceFile(Contract):
    """One source file handed to the extract stage: where it lives and what it says.

    The extract stage needs both halves — the text to parse and the path to anchor
    findings to — and they travel together often enough (a caller supplies several
    files, and one failing must not lose the others) that they are a contract rather
    than two loose arguments.
    """

    path: str = Field(
        min_length=1,
        description='Path this source came from, e.g. "migrations/003_orders.sql". '
        "Recorded as the provenance of every query extracted from it.",
    )
    content: str = Field(description="The source text.")


class SqlSource(SourceFile):
    """Backward-compatible SQL source with its parsing dialect."""

    dialect: str = "postgres"


class Provenance(Contract):
    """Where a finding is anchored back to in the diff."""

    file: str
    line: int | None = None
    symbol: str | None = Field(
        default=None,
        description="Enclosing method, repository, or migration name, when known.",
    )


class ExtractedQuery(Contract):
    """A single query candidate pulled out of the diff."""

    id: str = Field(description="Stable identifier for this query within the run.")
    kind: QueryKind
    text: str = Field(description="Query text as written in the source.")
    normalized: str | None = Field(
        default=None,
        description="Dialect-normalized form produced by sqlglot, when parseable.",
    )
    dialect: str = "postgres"
    provenance: Provenance
    parse_error: str | None = Field(
        default=None,
        description="Set when the query could not be parsed; it is then unanalyzable.",
    )
