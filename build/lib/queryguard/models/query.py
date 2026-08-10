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


class Hunk(Contract):
    """One contiguous changed region of a file, in both files' line coordinates.

    A pull request is a *change*, so knowing which lines it touched is what lets a
    later stage tell "this query is new" from "this query was already here and the
    author did not touch it". A hunk is how a diff says that.

    Both coordinate systems are kept because they answer different questions. The
    head side is the one findings are anchored to — a reviewer reads the pull
    request's own files, so a line number that refers to the base is a line number
    pointing at the wrong statement. The base side is retained because it is what
    makes a hunk checkable against the patch it came from.

    Line numbers are 1-based, as they are everywhere a file is quoted. A hunk that
    only deletes lines has ``head_lines == 0``; :attr:`head_end` is then *below*
    :attr:`head_start`, and :meth:`covers` is correctly false for every line, which
    is the honest answer — a pure deletion adds no head line to anchor to.
    """

    base_start: int = Field(
        ge=0, description="First line of the region in the base file. 0 for a new file."
    )
    base_lines: int = Field(ge=0, description="How many base lines the region spans.")
    head_start: int = Field(
        ge=0, description="First line of the region in the head file. 0 for a deleted file."
    )
    head_lines: int = Field(ge=0, description="How many head lines the region spans.")

    @property
    def head_end(self) -> int:
        """Last head line this hunk covers, inclusive."""
        return self.head_start + self.head_lines - 1

    def covers(self, line: int) -> bool:
        """Whether ``line``, in head coordinates, falls inside this hunk."""
        return self.head_start <= line <= self.head_end


class SourceFile(Contract):
    """One source file handed to the extract stage: where it lives and what it says.

    The extract stage needs both halves — the text to parse and the path to anchor
    findings to — and they travel together often enough (a caller supplies several
    files, and one failing must not lose the others) that they are a contract rather
    than two loose arguments.

    ``hunks`` is the third, optional half, and it is language-neutral in the same
    way ``path`` is: every language has diffs. It is empty for a source somebody
    handed us whole, and populated for one that came out of a pull request. Empty
    therefore reads as *the whole file is in scope*, which is what :meth:`is_changed`
    returns, and is why every caller that predates diffs keeps working unchanged.
    """

    path: str = Field(
        min_length=1,
        description='Path this source came from, e.g. "migrations/003_orders.sql". '
        "Recorded as the provenance of every query extracted from it.",
    )
    content: str = Field(
        description="The source text. For a diff-derived source this is the file as "
        "it stands at the head commit, in full — not the patch, and not the changed "
        "lines alone."
    )
    hunks: list[Hunk] = Field(
        default_factory=list,
        description="Regions the pull request changed, in head coordinates. Empty "
        "when the source did not come from a diff.",
    )

    def is_changed(self, line: int) -> bool:
        """Whether ``line`` was touched by the change this source came from.

        A source with no hunks did not come from a diff, so nothing is known to be
        unchanged and every line answers true. That default is deliberate: the
        alternative would silently drop every finding from every source the API is
        handed directly.
        """
        if not self.hunks:
            return True
        return any(hunk.covers(line) for hunk in self.hunks)


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
