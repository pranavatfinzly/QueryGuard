"""Select the extractor for one source file."""

from __future__ import annotations

from pathlib import Path

from queryguard.models.query import ExtractedQuery
from queryguard.pipeline.extract.java import extract_java
from queryguard.pipeline.extract.sql import extract_from_sql

__all__ = ["extract_queries"]


def extract_queries(path: str, content: str) -> list[ExtractedQuery]:
    """Extract queries from one source according to its file extension."""
    match Path(path).suffix.lower():
        case ".sql":
            return extract_from_sql(path, content)
        case ".java":
            return extract_java(path, content)
        case _:
            return []
