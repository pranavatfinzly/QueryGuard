"""Tests for selecting a source-language extractor."""

from __future__ import annotations

import pytest

from queryguard.models import ExtractedQuery, Provenance, QueryKind
from queryguard.pipeline.extract import dispatcher


def query() -> ExtractedQuery:
    """A distinctive query object used to prove dispatcher pass-through."""
    return ExtractedQuery(
        id="migration.sql:3",
        kind=QueryKind.RAW_SQL,
        text="SELECT id FROM orders",
        provenance=Provenance(file="migration.sql", line=3),
    )


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("migration.sql", "SELECT 1"),
        ("MIGRATION.SQL", "SELECT 1"),
        ("db/migrations/V3__orders.Sql", ""),
    ],
)
def test_sql_files_are_delegated_without_altering_extractor_output(
    monkeypatch: pytest.MonkeyPatch, path: str, content: str
) -> None:
    expected = [query()]
    calls: list[tuple[str, str]] = []

    def extract_sql(received_path: str, received_content: str) -> list[ExtractedQuery]:
        calls.append((received_path, received_content))
        return expected

    monkeypatch.setattr(dispatcher, "extract_from_sql", extract_sql)

    assert dispatcher.extract_queries(path, content) is expected
    assert calls == [(path, content)]


def test_java_files_are_delegated_to_the_java_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = [query()]
    calls: list[tuple[str, str]] = []

    def extract_java(received_path: str, received_content: str) -> list[ExtractedQuery]:
        calls.append((received_path, received_content))
        return expected

    monkeypatch.setattr(dispatcher, "extract_java", extract_java)

    assert dispatcher.extract_queries("src/Repository.JAVA", "") is expected
    assert calls == [("src/Repository.JAVA", "")]


@pytest.mark.parametrize("path", ["README.md", "script.kt", "Dockerfile", "query.sql.bak"])
def test_unsupported_extensions_return_no_queries(path: str) -> None:
    assert dispatcher.extract_queries(path, "SELECT * FROM orders") == []


def test_empty_sql_file_is_delegated_to_the_sql_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def extract_sql(path: str, content: str) -> list[ExtractedQuery]:
        calls.append((path, content))
        return []

    monkeypatch.setattr(dispatcher, "extract_from_sql", extract_sql)

    assert dispatcher.extract_queries("empty.sql", "") == []
    assert calls == [("empty.sql", "")]


def test_dispatcher_does_not_parse_java_as_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(path: str, content: str) -> list[ExtractedQuery]:
        raise AssertionError("the SQL extractor must not receive an unsupported file")

    monkeypatch.setattr(dispatcher, "extract_from_sql", fail_if_called)
    monkeypatch.setattr(dispatcher, "extract_java", lambda path, content: [])

    assert dispatcher.extract_queries("src/Repository.java", "SELECT * FROM orders") == []
