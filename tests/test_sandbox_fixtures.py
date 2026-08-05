"""Integrity tests for the queryguard-sandbox fixture project.

The sandbox exists so QueryGuard has known-bad input with known-good
counterparts. These tests guard the fixture itself: if someone "fixes" a planted
bug or adds the missing index, the rules that depend on it start silently passing
against nothing. They assert source-level facts only — no JVM, no database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlglot

SANDBOX = Path(__file__).resolve().parent.parent / "queryguard-sandbox"
JAVA_ROOT = SANDBOX / "src/main/java/com/queryguard/sandbox"
MIGRATION = SANDBOX / "src/main/resources/db/migration/V1__create_tables.sql"

PLANTED_BUGS = {
    "native_select_star_no_where": JAVA_ROOT / "repository/OrderRepository.java",
    "jpql_unindexed_column": JAVA_ROOT / "repository/CustomerRepository.java",
    "n_plus_one_in_loop": JAVA_ROOT / "service/ReportingService.java",
    "update_no_where": JAVA_ROOT / "repository/CustomerRepository.java",
}


def test_sandbox_project_exists() -> None:
    assert (SANDBOX / "pom.xml").is_file()
    assert MIGRATION.is_file()


@pytest.mark.parametrize("name", sorted(PLANTED_BUGS))
def test_planted_bug_marker_is_present(name: str) -> None:
    source = PLANTED_BUGS[name].read_text(encoding="utf-8")
    assert "PLANTED BUG:" in source


def test_all_four_planted_bugs_are_present() -> None:
    total = sum(
        path.read_text(encoding="utf-8").count("PLANTED BUG:")
        for path in sorted(set(PLANTED_BUGS.values()))
    )
    assert total == 4, f"expected exactly 4 planted bugs, found {total}"


def test_bug_one_is_select_star_with_no_where() -> None:
    source = (JAVA_ROOT / "repository/OrderRepository.java").read_text(encoding="utf-8")
    assert 'value = "SELECT * FROM orders"' in source
    assert "nativeQuery = true" in source

    parsed = sqlglot.parse_one("SELECT * FROM orders", read="postgres")
    assert parsed.find(sqlglot.exp.Star) is not None
    assert parsed.find(sqlglot.exp.Where) is None


def test_bug_two_filters_a_column_the_migration_leaves_unindexed() -> None:
    source = (JAVA_ROOT / "repository/CustomerRepository.java").read_text(encoding="utf-8")
    assert "WHERE c.country = :country" in source

    # The fixture only works while country has no index.
    indexed_columns = {
        column.name
        for statement in sqlglot.parse(MIGRATION.read_text(encoding="utf-8"), read="postgres")
        if isinstance(statement, sqlglot.exp.Create) and statement.kind == "INDEX"
        for column in statement.find_all(sqlglot.exp.Column)
    }
    assert "country" not in indexed_columns
    # Sanity check that the extraction above actually found the real indexes.
    assert {"customer_id", "placed_at", "order_id"} <= indexed_columns


def test_bug_three_calls_a_derived_method_inside_a_loop() -> None:
    source = (JAVA_ROOT / "service/ReportingService.java").read_text(encoding="utf-8")
    loop_start = source.index("for (Customer customer : customers)")
    loop_body = source[loop_start : source.index("return summaries;", loop_start)]
    assert "orderRepository.findByCustomerId(" in loop_body


def test_bug_four_is_an_update_with_no_where() -> None:
    source = (JAVA_ROOT / "repository/CustomerRepository.java").read_text(encoding="utf-8")
    assert '@Query("UPDATE Customer c SET c.loyaltyTier = :tier")' in source


def test_destructive_fixture_is_guarded_and_defaults_off() -> None:
    properties = (SANDBOX / "src/main/resources/application.properties").read_text(
        encoding="utf-8"
    )
    assert "sandbox.allow-destructive-fixtures=false" in properties

    service = (JAVA_ROOT / "service/MaintenanceService.java").read_text(encoding="utf-8")
    assert "if (!destructiveFixturesAllowed)" in service
    assert "throw new IllegalStateException" in service


def test_healthy_counterparts_exist_for_false_positive_guarding() -> None:
    expected = {
        "repository/OrderRepository.java": "exportRecentOrders",
        "repository/CustomerRepository.java": "promoteHighValueCustomers",
        "service/ReportingService.java": "buildCustomerOrderSummaryBatched",
        "repository/OrderItemRepository.java": "findByOrderIdIn",
    }
    for relative_path, method in expected.items():
        source = (JAVA_ROOT / relative_path).read_text(encoding="utf-8")
        assert method in source, f"{relative_path} is missing {method}"


def test_migration_parses_as_postgres() -> None:
    statements = [s for s in sqlglot.parse(MIGRATION.read_text(encoding="utf-8"), read="postgres") if s]
    # For CREATE TABLE, `statement.this` is a Schema wrapping the Table — reach
    # for the Table node rather than reading `.name` off the wrapper.
    tables = {
        statement.find(sqlglot.exp.Table).name
        for statement in statements
        if isinstance(statement, sqlglot.exp.Create) and statement.kind == "TABLE"
    }
    assert tables == {"customers", "orders", "order_items"}


def test_seeder_uses_a_fixed_random_seed() -> None:
    seeder = (JAVA_ROOT / "seed/DataSeeder.java").read_text(encoding="utf-8")
    # Reproducible plans depend on reproducible data.
    assert "new Random(randomSeed)" in seeder
    assert "sandbox.seed.random-seed:20260805" in seeder
