"""Stage 2 (derived) — Spring Data method name to query semantics.

A repository method name *is* a query. ``findByCustomerIdAndStatusOrderByCreatedAtDesc``
declares its predicates, its conjunction, and its sort without a line of SQL, so
the name has to be decoded before any rule can reason about it.

Decoding matters beyond the obvious: the emitted SQL is often not what the name
suggests. ``findByCustomerId`` on an entity whose ``customer`` is a ``@ManyToOne``
compiles to a *join* against ``customers`` filtered on the parent's primary key,
not a bare ``orders.customer_id = ?`` predicate — so a rule that assumes the
latter will reason about a query that was never issued.
"""

from __future__ import annotations

from queryguard.models.query import ExtractedQuery

__all__ = ["parse_derived_method"]


def parse_derived_method(
    method_name: str,
    entity: str,
    path: str,
    line: int | None = None,
) -> ExtractedQuery | None:
    """Decode a Spring Data derived method name into a query.

    Returns ``None`` when the name is not a derived query (an ordinary helper, or
    a method carrying its own ``@Query``, which the Java extractor handles
    instead).
    """
    raise NotImplementedError(
        "extract.derived.parse_derived_method is not implemented yet"
    )
