"""Typed contracts exchanged between pipeline stages.

Stages pass these models to each other — never bare dicts or tuples. Adding a
field to a stage's output means adding it here first.
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


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


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


class Evidence(BaseModel):
    """Supporting detail for a finding: a plan excerpt, a cost delta, a snippet."""

    label: str
    detail: str


class Suggestion(BaseModel):
    """A proposed fix, and the measured impact of applying it where available."""

    description: str
    sql: str | None = Field(
        default=None,
        description="DDL or rewritten query, e.g. a CREATE INDEX statement.",
    )
    cost_before: float | None = None
    cost_after: float | None = None


class Finding(BaseModel):
    """One reportable problem, from any analysis stage."""

    rule_id: str
    severity: Severity
    title: str
    explanation: str
    provenance: Provenance
    query_id: str | None = None
    query_ids: list[str] = Field(
        default_factory=list,
        description="Populated for cross-query findings such as N+1 patterns.",
    )
    evidence: list[Evidence] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    confidence: float | None = Field(
        default=None,
        description="Set for LLM-derived findings that could not be verified.",
    )


class RunContext(BaseModel):
    """Identifies the PR under analysis and the run itself."""

    run_id: str
    repo: str = Field(description='Owner/name, e.g. "acme/billing-service".')
    pr_number: int
    base_sha: str | None = None
    head_sha: str | None = None


class Report(BaseModel):
    """Merged output of every stage; input to the Markdown renderer."""

    context: RunContext
    queries: list[ExtractedQuery] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    degraded_stages: list[str] = Field(
        default_factory=list,
        description="Stages that failed soft; surfaced in the report as caveats.",
    )
