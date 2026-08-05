"""Query contracts — what the extract stage produces.

See :mod:`queryguard.models` for why these live in models rather than beside the
stage that builds them.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class QueryKind(str, Enum):
    """Where a query came from, which decides how it is parsed and bound."""

    RAW_SQL = "raw_sql"
    JPQL = "jpql"
    HQL = "hql"
    JPA_NATIVE = "jpa_native"
    SPRING_DATA_DERIVED = "spring_data_derived"


class Provenance(BaseModel):
    """Where a finding is anchored back to in the diff."""

    file: str
    line: int | None = None
    symbol: str | None = Field(
        default=None,
        description="Enclosing method, repository, or migration name, when known.",
    )


class ExtractedQuery(BaseModel):
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
