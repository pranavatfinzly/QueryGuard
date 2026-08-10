"""Tests for the Liquibase changelog loader.

Structural behaviour (createTable, addColumn, createIndex, primary keys, unique
constraints, dropIndex, recursive includes, declared order, composite indexes,
unknown tables) is exercised with small synthetic changelogs written directly to
``tmp_path`` — no point vendoring a real repository's changelog just to prove a
tag is read correctly.

The acceptance scenario at the bottom is the one exception: it uses the two
committed fixtures under ``tests/fixtures/liquibase/``, modeled on the real
``sweep_payment_tracking`` table audited in galaxy-payment-service, because that
real-world correspondence — a genuine table, a genuine native query, a genuine
index — is the point of that test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from queryguard.db.liquibase import (
    LiquibaseParseError,
    build_table_schemas,
    load_liquibase_schema,
    load_schema_from_settings,
    resolve_changelog_files,
)
from queryguard.models.query import ExtractedQuery, Provenance, QueryKind
from queryguard.pipeline.static_rules import RuleEngine
from queryguard.pipeline.static_rules.rules.unindexed_filter import UnindexedFilterRule

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "liquibase"

_NS = 'xmlns="http://www.liquibase.org/xml/ns/dbchangelog"'


def _changelog(tmp_path: Path, name: str, body: str) -> Path:
    """Write one minimal, valid changelog file and return its path."""
    path = tmp_path / name
    path.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<databaseChangeLog {_NS}>\n{body}\n</databaseChangeLog>\n'
    )
    return path


# --- 1. createTable -------------------------------------------------------


def test_create_table_records_columns_with_no_indexes_by_default(tmp_path: Path) -> None:
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="widgets">
                <column name="id" type="bigint"/>
                <column name="label" type="varchar(50)"/>
            </createTable>
        </changeSet>
        """,
    )

    schemas = build_table_schemas(root)

    assert schemas["widgets"].column_types == {"id": "bigint", "label": "varchar(50)"}
    assert schemas["widgets"].indexed_columns == frozenset()


# --- 2. addColumn -----------------------------------------------------------


def test_add_column_extends_a_previously_created_table(tmp_path: Path) -> None:
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="widgets">
                <column name="id" type="bigint"/>
            </createTable>
        </changeSet>
        <changeSet id="2" author="t">
            <addColumn tableName="widgets">
                <column name="status" type="varchar(20)"/>
            </addColumn>
        </changeSet>
        """,
    )

    schemas = build_table_schemas(root)

    assert schemas["widgets"].column_types == {"id": "bigint", "status": "varchar(20)"}


# --- 3. createIndex ----------------------------------------------------------


def test_create_index_marks_its_column_as_indexed(tmp_path: Path) -> None:
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="widgets">
                <column name="status" type="varchar(20)"/>
            </createTable>
            <createIndex indexName="idx_widgets_status" tableName="widgets">
                <column name="status"/>
            </createIndex>
        </changeSet>
        """,
    )

    schemas = build_table_schemas(root)

    assert schemas["widgets"].indexed_columns == frozenset({"status"})


# --- 4. Primary key indexing --------------------------------------------------


def test_inline_primary_key_constraint_counts_as_indexed(tmp_path: Path) -> None:
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="widgets">
                <column name="id" type="bigint">
                    <constraints primaryKey="true" nullable="false"/>
                </column>
            </createTable>
        </changeSet>
        """,
    )

    assert build_table_schemas(root)["widgets"].indexed_columns == frozenset({"id"})


def test_add_primary_key_indexes_the_leading_column_only(tmp_path: Path) -> None:
    """Mirrors the audited chain's partition pattern: a composite PK added
    structurally after the table exists (``id, payment_date``), where only
    ``id`` is a real single-column lookup path."""
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="ach_details">
                <column name="id" type="varchar(50)"/>
                <column name="payment_date" type="date"/>
            </createTable>
        </changeSet>
        <changeSet id="2" author="t">
            <addPrimaryKey tableName="ach_details" columnNames="id, payment_date" constraintName="pk_ach_details"/>
        </changeSet>
        """,
    )

    schemas = build_table_schemas(root)

    assert schemas["ach_details"].indexed_columns == frozenset({"id"})
    assert "payment_date" not in schemas["ach_details"].indexed_columns


# --- 5. Unique constraint indexing --------------------------------------------


def test_inline_unique_constraint_counts_as_indexed(tmp_path: Path) -> None:
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="customers">
                <column name="email" type="varchar(255)">
                    <constraints unique="true"/>
                </column>
            </createTable>
        </changeSet>
        """,
    )

    assert build_table_schemas(root)["customers"].indexed_columns == frozenset({"email"})


def test_add_unique_constraint_indexes_the_leading_column(tmp_path: Path) -> None:
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="auto_translation">
                <column name="type" type="varchar(255)"/>
                <column name="old_value" type="varchar(255)"/>
            </createTable>
        </changeSet>
        <changeSet id="2" author="t">
            <addUniqueConstraint tableName="auto_translation" columnNames="type, old_value" constraintName="uc_type_old_value"/>
        </changeSet>
        """,
    )

    schemas = build_table_schemas(root)

    assert schemas["auto_translation"].indexed_columns == frozenset({"type"})
    assert "old_value" not in schemas["auto_translation"].indexed_columns


# --- 6. dropIndex --------------------------------------------------------------


def test_drop_index_removes_a_column_no_other_index_covers(tmp_path: Path) -> None:
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="widgets">
                <column name="status" type="varchar(20)"/>
            </createTable>
            <createIndex indexName="idx_widgets_status" tableName="widgets">
                <column name="status"/>
            </createIndex>
        </changeSet>
        <changeSet id="2" author="t">
            <dropIndex indexName="idx_widgets_status" tableName="widgets"/>
        </changeSet>
        """,
    )

    assert build_table_schemas(root)["widgets"].indexed_columns == frozenset()


def test_drop_index_leaves_a_column_still_covered_by_another_index(tmp_path: Path) -> None:
    """The real memopost_tracker.payment_id case: two independently-named
    indexes both lead with the same column. Dropping one must not un-index it."""
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="memopost_tracker">
                <column name="payment_id" type="bigint"/>
                <column name="memo_post_type" type="varchar(45)"/>
            </createTable>
            <createIndex indexName="idx_payment_id_and_memotype" tableName="memopost_tracker">
                <column name="payment_id"/>
                <column name="memo_post_type"/>
            </createIndex>
            <createIndex indexName="idx_memopost_tracker_payment_id" tableName="memopost_tracker">
                <column name="payment_id"/>
            </createIndex>
        </changeSet>
        <changeSet id="2" author="t">
            <dropIndex indexName="idx_memopost_tracker_payment_id" tableName="memopost_tracker"/>
        </changeSet>
        """,
    )

    assert build_table_schemas(root)["memopost_tracker"].indexed_columns == frozenset(
        {"payment_id"}
    )


# --- 7. Recursive include resolution -------------------------------------------


def test_includes_resolve_recursively_through_multiple_levels(tmp_path: Path) -> None:
    leaf = _changelog(
        tmp_path,
        "leaf.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="widgets">
                <column name="id" type="bigint"/>
            </createTable>
        </changeSet>
        """,
    )
    mid = _changelog(
        tmp_path, "mid.xml", '<include file="leaf.xml" relativeToChangelogFile="true"/>'
    )
    root = _changelog(
        tmp_path, "root.xml", '<include file="mid.xml" relativeToChangelogFile="true"/>'
    )

    assert resolve_changelog_files(root) == [root, mid, leaf]
    assert "widgets" in build_table_schemas(root)


# --- 8. Declared-order processing ----------------------------------------------


def test_changesets_apply_in_declared_include_order_not_alphabetical(tmp_path: Path) -> None:
    """File names are chosen so alphabetical order would reverse the real one:
    if the loader processed ``z_second.xml`` before ``a_first.xml``, the drop
    would run before the create and the index would incorrectly survive."""
    _changelog(
        tmp_path,
        "a_first.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="widgets">
                <column name="status" type="varchar(20)"/>
            </createTable>
            <createIndex indexName="idx_widgets_status" tableName="widgets">
                <column name="status"/>
            </createIndex>
        </changeSet>
        """,
    )
    _changelog(
        tmp_path,
        "z_second.xml",
        """
        <changeSet id="1" author="t">
            <dropIndex indexName="idx_widgets_status" tableName="widgets"/>
        </changeSet>
        """,
    )
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <include file="z_second.xml" relativeToChangelogFile="true"/>
        <include file="a_first.xml" relativeToChangelogFile="true"/>
        """,
    )

    # Declared order is z_second then a_first: the drop (for an index that does
    # not exist yet) is a no-op, then a_first creates the index — which must
    # therefore still be present, proving order followed the <include>
    # declaration rather than the filesystem/alphabetical name.
    assert build_table_schemas(root)["widgets"].indexed_columns == frozenset({"status"})


# --- 9. Composite index leading-column behaviour --------------------------------


def test_composite_index_only_indexes_its_leading_column(tmp_path: Path) -> None:
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="bulk_file_payment_initiation">
                <column name="file_number" type="varchar(50)"/>
                <column name="message_type" type="varchar(50)"/>
                <column name="status" type="varchar(30)"/>
            </createTable>
            <createIndex indexName="idx_bfpi_file_number" tableName="bulk_file_payment_initiation">
                <column name="file_number"/>
                <column name="message_type"/>
                <column name="status"/>
            </createIndex>
        </changeSet>
        """,
    )

    indexed = build_table_schemas(root)["bulk_file_payment_initiation"].indexed_columns

    assert indexed == frozenset({"file_number"})
    assert "message_type" not in indexed
    assert "status" not in indexed


# --- 10. Unknown table behaviour -------------------------------------------------


def test_unknown_table_reports_none_through_the_provider(tmp_path: Path) -> None:
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <changeSet id="1" author="t">
            <createTable tableName="widgets">
                <column name="id" type="bigint"/>
            </createTable>
        </changeSet>
        """,
    )

    provider = load_liquibase_schema(root)

    assert provider.indexed_columns("widgets") == frozenset()
    assert provider.indexed_columns("nonexistent_table") is None


# --- Supporting behaviour: properties, missing files, fail-soft loading --------


def test_property_placeholders_are_substituted_in_column_types(tmp_path: Path) -> None:
    root = _changelog(
        tmp_path,
        "root.xml",
        """
        <property name="boolean.type" value="boolean"/>
        <changeSet id="1" author="t">
            <createTable tableName="widgets">
                <column name="active" type="${boolean.type}"/>
            </createTable>
        </changeSet>
        """,
    )

    assert build_table_schemas(root)["widgets"].column_types == {"active": "boolean"}


def test_missing_changelog_file_raises_liquibase_parse_error(tmp_path: Path) -> None:
    with pytest.raises(LiquibaseParseError):
        build_table_schemas(tmp_path / "does_not_exist.xml")


def test_load_schema_from_settings_is_silent_when_unconfigured() -> None:
    from queryguard.pipeline.static_rules import UNKNOWN_SCHEMA

    assert load_schema_from_settings(None) is UNKNOWN_SCHEMA


def test_load_schema_from_settings_fails_soft_on_a_bad_path(tmp_path: Path) -> None:
    from queryguard.pipeline.static_rules import UNKNOWN_SCHEMA

    assert load_schema_from_settings(str(tmp_path / "missing.xml")) is UNKNOWN_SCHEMA


# --- Raw-SQL limitation (Phase 3) -----------------------------------------------


def test_raw_sql_schema_changes_are_not_inferred() -> None:
    """Regression guard for the documented limitation: a column and index added
    entirely inside a <sql> block (the real PG-56.xml shape) must stay invisible
    to the loader rather than being guessed at from the SQL text."""
    schemas = build_table_schemas(FIXTURES / "raw_sql_only.xml")

    # The changeset only ever mentions `widgets` inside a <sql> string, never a
    # structured tag — so the loader must not have created any entry for it.
    assert "widgets" not in schemas


# --- Acceptance scenario (real galaxy-payment-service audit finding) -----------


def _delete_by_payment_id_query() -> ExtractedQuery:
    """The real native query from SweepPaymentTrackingRepository.deleteByPaymentId."""
    return ExtractedQuery(
        id="q1",
        kind=QueryKind.SQL,
        text="DELETE FROM sweep_payment_tracking WHERE payment_id = :paymentId",
        provenance=Provenance(file="SweepPaymentTrackingRepository.java", line=36),
    )


def test_acceptance_index_present_produces_no_unindexed_filter_finding() -> None:
    schema = load_liquibase_schema(FIXTURES / "sweep_payment_tracking_with_index.xml")

    findings = RuleEngine(rules=[UnindexedFilterRule()], schema=schema).analyze(
        [_delete_by_payment_id_query()]
    )

    assert findings == []


def test_acceptance_index_absent_produces_an_unindexed_filter_finding() -> None:
    schema = load_liquibase_schema(FIXTURES / "sweep_payment_tracking_without_index.xml")

    findings = RuleEngine(rules=[UnindexedFilterRule()], schema=schema).analyze(
        [_delete_by_payment_id_query()]
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "unindexed-filter"
    assert "payment_id" in findings[0].title
