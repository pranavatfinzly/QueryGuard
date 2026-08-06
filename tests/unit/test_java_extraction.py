"""Tests for narrow Spring Data JPQL ``@Query`` extraction."""

from __future__ import annotations

import pytest

from queryguard.models import QueryKind
from queryguard.pipeline.extract.java import extract_java


def test_extracts_a_single_query_from_a_repository_interface() -> None:
    content = """@Repository
public interface CustomerRepository {

    @Query("SELECT c FROM Customer c WHERE c.id = :id")
    Customer findCustomer(Long id);
}
"""

    (query,) = extract_java("src/CustomerRepository.java", content)

    assert query.id == "src/CustomerRepository.java:1"
    assert query.kind is QueryKind.JPQL
    assert query.text == "SELECT c FROM Customer c WHERE c.id = :id"
    assert query.provenance.file == "src/CustomerRepository.java"
    assert query.provenance.line == 4


def test_extracts_multiple_query_annotations_in_source_order() -> None:
    content = """public interface CustomerRepository {
    @Query("SELECT c FROM Customer c")
    List<Customer> customers();

    @Query("SELECT c FROM Customer c WHERE c.status = :status")
    List<Customer> byStatus(String status);
}
"""

    queries = extract_java("CustomerRepository.java", content)

    assert [query.id for query in queries] == [
        "CustomerRepository.java:1",
        "CustomerRepository.java:2",
    ]
    assert [query.text for query in queries] == [
        "SELECT c FROM Customer c",
        "SELECT c FROM Customer c WHERE c.status = :status",
    ]


def test_extracts_a_query_from_a_service_class() -> None:
    content = """@Service
public class CustomerService {
    @Query("SELECT c FROM Customer c")
    List<Customer> customers();
}
"""

    (query,) = extract_java("src/CustomerService.java", content)

    assert query.text == "SELECT c FROM Customer c"
    assert query.provenance.line == 3


def test_preserves_multiline_text_block_query_and_its_start_line() -> None:
    content = '''package com.example;

public interface CustomerRepository {
    @Query("""
SELECT c
FROM Customer c
WHERE c.status = :status
""")
    List<Customer> byStatus(String status);
}
'''

    (query,) = extract_java("src/CustomerRepository.java", content)

    assert query.text == "SELECT c\nFROM Customer c\nWHERE c.status = :status\n"
    assert query.provenance.line == 5
    assert query.kind is QueryKind.JPQL


@pytest.mark.parametrize(
    "content",
    [
        "",
        "public class CustomerService {}",
        '@Query("SELECT c FROM Customer c"',
        '@Query("SELECT c FROM Customer c", nativeQuery = true)',
        '@Query("SELECT " + "c FROM Customer c")',
        '@Query(value = "SELECT c FROM Customer c")',
    ],
)
def test_unsupported_or_malformed_annotations_produce_no_queries(content: str) -> None:
    assert extract_java("CustomerRepository.java", content) == []
