"""Stage 2 (derived) — Spring Data method names as queries.

Three responsibilities, deliberately three functions, because they change for
different reasons and the next framework needs them separately:

1. :func:`parse_derived_query` — *decode a name*. Spring Data's method-name
   grammar in, :class:`DerivedQuery` out. Knows nothing about SQL, files, or
   lines.
2. :func:`render_derived_query` — *say what it means in SQL*. Takes the decoded
   semantics and a table name; produces text the static rules can parse.
3. :func:`parse_derived_method` — *anchor it to the source*. Glues the two and
   attaches provenance.

The seam that matters is :class:`DerivedQuery`. Method-name grammars are not
unique to Spring Data — Micronaut Data and Spring Data JDBC share the shape —
so a second framework's decoder can target the same IR and reuse the renderer
unchanged. It is also what the planned derived-method fan-out rule needs:
"this method returns a collection and is called per row" is a question about
semantics, and reading it back out of rendered SQL text would mean parsing what
we just printed.

The decoder is narrow on purpose and says so by returning None. A name it does
not fully understand produces no query rather than a guessed one, because a
finding against SQL that Spring Data never generates is worse than silence — see
the caution in CLAUDE.md about ``findByCustomerId`` compiling to a join.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from queryguard.models.query import ExtractedQuery, Provenance, QueryKind
from queryguard.pipeline.extract.base import symbol_query_id

__all__ = [
    "DerivedOperation",
    "DerivedQuery",
    "EqualityPredicate",
    "entity_table",
    "parse_derived_method",
    "parse_derived_query",
    "render_derived_query",
]


class DerivedOperation(str, Enum):
    """The supported Spring Data derived-method operations."""

    FIND = "find"
    COUNT = "count"
    EXISTS = "exists"
    DELETE = "delete"


@dataclass(frozen=True)
class EqualityPredicate:
    """One equality predicate from a derived-method property segment.

    ``property_name`` is already rendered as a SQL identifier, because the
    camelCase-to-snake_case convention is Spring Data's own mapping default and
    therefore part of decoding the name, not of printing it.
    """

    property_name: str


@dataclass(frozen=True)
class DerivedQuery:
    """Framework-neutral semantics of one derived-method name.

    Frozen, and the contract between decoding and everything downstream. The
    fields beyond ``operation`` and ``predicates`` are the grammar this decoder
    does not accept yet; they are declared so that widening the decoder does not
    change the IR's shape underneath the renderer and the planned fan-out rule.
    """

    operation: DerivedOperation
    predicates: tuple[EqualityPredicate, ...]
    ordering: str | None = None
    limit: int | None = None
    distinct: bool = False


DERIVED_METHOD = re.compile(
    r"^(?P<operation>find|count|exists|delete)By(?P<criteria>[A-Z][A-Za-z0-9]*)$"
)
UNSUPPORTED_CONNECTOR = re.compile(r"[a-z0-9]Or(?=[A-Z])|OrderBy")
UNSUPPORTED_SUFFIX = re.compile(
    r"(?:Between|Like|Containing|StartsWith|EndsWith|LessThan|GreaterThan|IgnoreCase|"
    r"NotIn|In|True|False|IsNull|IsNotNull)$"
)
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def parse_derived_query(method_name: str) -> DerivedQuery | None:
    """Decode a Spring Data method name, or return None if it is not understood.

    Accepts ``find``/``count``/``exists``/``delete`` with equality predicates
    joined by ``And``. Every other operator, ``Or``, ``OrderBy``, ``Top``/
    ``First``, nested properties, and malformed names are rejected outright.
    """
    match = DERIVED_METHOD.fullmatch(method_name)
    if match is None:
        return None

    criteria = match.group("criteria")
    if UNSUPPORTED_CONNECTOR.search(criteria) is not None:
        return None

    property_names = criteria.split("And")
    if any(
        not property_name or UNSUPPORTED_SUFFIX.search(property_name) is not None
        for property_name in property_names
    ):
        return None

    return DerivedQuery(
        operation=DerivedOperation(match.group("operation")),
        predicates=tuple(
            EqualityPredicate(property_name=_camel_to_snake(property_name))
            for property_name in property_names
        ),
    )


def render_derived_query(derived: DerivedQuery, table: str) -> str:
    """Render decoded semantics as the SQL-shaped text the rules analyze.

    Built by formatting rather than through a sqlglot AST, which is the mirror of
    the rule CLAUDE.md states for reading SQL, so it is worth saying why it is
    safe here and where the line is. Every identifier reaching this function has
    already passed :data:`DERIVED_METHOD`, whose character class is
    ``[A-Za-z0-9]`` — there is no quoting decision to get wrong and no untrusted
    text to inject. What the formatting buys is a *stable, readable* rendering:
    this text is quoted back to a reviewer in the PR comment, and a sqlglot
    round-trip would reformat it for no gain the reviewer can see.

    The moment the decoder accepts something with real syntax to it — ordering,
    limits, joins for nested properties — that reasoning expires and this should
    build an expression tree instead. The IR boundary above is what makes that a
    change to this function alone.
    """
    where = "\n".join(
        [
            f"WHERE {derived.predicates[0].property_name} = ?",
            *[f"AND {predicate.property_name} = ?" for predicate in derived.predicates[1:]],
        ]
    )

    match derived.operation:
        case DerivedOperation.FIND:
            return f"SELECT *\nFROM {table}\n{where}"
        case DerivedOperation.COUNT:
            return f"SELECT COUNT(*)\nFROM {table}\n{where}"
        case DerivedOperation.EXISTS:
            return f"SELECT 1\nFROM {table}\n{where}"
        case DerivedOperation.DELETE:
            return f"DELETE\nFROM {table}\n{where}"


def parse_derived_method(
    method_name: str,
    entity: str,
    path: str,
    line: int | None = None,
) -> ExtractedQuery | None:
    """Render a supported Spring Data derived method as an ``ExtractedQuery``.

    The composition of :func:`parse_derived_query`, :func:`entity_table`, and
    :func:`render_derived_query`, with provenance attached. Returns None for any
    name the decoder does not accept.
    """
    derived = parse_derived_query(method_name)
    if derived is None:
        return None

    return ExtractedQuery(
        id=symbol_query_id(path, method_name),
        kind=QueryKind.SPRING_DATA_DERIVED,
        text=render_derived_query(derived, entity_table(entity)),
        provenance=Provenance(file=path, line=line, symbol=method_name),
    )


def entity_table(entity: str) -> str:
    """A stable table placeholder from an entity or repository interface name.

    A placeholder, not a resolved table: the real name depends on ``@Table``,
    the naming strategy, and the entity's own fields, none of which are visible
    from a repository interface. Stable is what matters here — the same input
    must always produce the same text, or an unchanged PR would produce a
    different comment on re-run.
    """
    entity_name = entity.removesuffix("Repository")
    return _camel_to_snake(entity_name) if entity_name else "unknown_entity"


def _camel_to_snake(value: str) -> str:
    """Render a Java property or type name as a simple SQL identifier."""
    return CAMEL_BOUNDARY.sub("_", value).lower()
