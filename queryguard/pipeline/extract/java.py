"""Stage 2 (Java) — JavaParser sidecar client.

Walks Java sources for ``@Query`` annotations, ``createQuery`` /
``createNativeQuery`` calls, and Spring Data repository method names.

The sidecar only parses and emits JSON; all analysis stays here on the Python
side so the rules have one home. Its JSON shape is a versioned contract —
changing it means updating :mod:`queryguard.models.query` and the fixtures
together.
"""

from __future__ import annotations

from queryguard.models.query import ExtractedQuery

__all__ = ["extract_from_java"]


def extract_from_java(path: str, content: str) -> list[ExtractedQuery]:
    """Extract JPQL/HQL, native queries, and derived methods from a Java source.

    Repository method names are handed to
    :func:`queryguard.pipeline.extract.derived.parse_derived_method` to recover
    their query semantics.
    """
    raise NotImplementedError("extract.java.extract_from_java is not implemented yet")
