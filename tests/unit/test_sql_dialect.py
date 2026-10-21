"""SQL dialect: detection from the JDBC URL, and its effect on a real run."""

from __future__ import annotations

import dataclasses

import pytest

from queryguard import cli
from queryguard.config import override_settings
from queryguard.db.dialect import detect_sql_dialect, is_known_dialect
from queryguard.models.query import SourceFile
from queryguard.pipeline.runner import AnalysisRunner
from tests.conftest import RecordedGitHub, RecordedPullRequest

PROPS = "src/main/resources/application.properties"
YAML = "src/main/resources/application.yml"


def _reader(files: dict[str, str]):  # type: ignore[no-untyped-def]
    return lambda path: files.get(path)


# --- detection --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("jdbc:mysql://host:3306/db", "mysql"),
        ("jdbc:mariadb://host/db", "mysql"),
        ("jdbc:postgresql://host/db", "postgres"),
        ("jdbc:oracle:thin:@//host:1521/svc", "oracle"),
        ("jdbc:sqlserver://host;databaseName=x", "tsql"),
        ("JDBC:MYSQL://host/db", "mysql"),
    ],
)
def test_the_jdbc_protocol_names_the_dialect(url: str, expected: str) -> None:
    files = {PROPS: f"spring.datasource.url={url}\n"}

    assert detect_sql_dialect(_reader(files)) == expected


def test_a_yaml_config_is_read_too() -> None:
    files = {YAML: "spring:\n  datasource:\n    url: jdbc:mysql://h/db\n"}

    assert detect_sql_dialect(_reader(files)) == "mysql"


@pytest.mark.parametrize(
    "text",
    [
        "spring.datasource.url=${DB_URL}\n",  # a placeholder says nothing
        "spring.datasource.url=jdbc:h2:mem:test\n",  # in-memory test database
        "# spring.datasource.url=jdbc:mysql://h/db\n",  # commented out
        "spring.application.name=svc\n",
        "",
    ],
)
def test_no_answer_is_better_than_a_wrong_one(text: str) -> None:
    assert detect_sql_dialect(_reader({PROPS: text})) is None


def test_a_missing_config_is_no_answer_not_an_error() -> None:
    assert detect_sql_dialect(_reader({})) is None


def test_h2_does_not_mask_the_real_database_in_a_later_file() -> None:
    files = {
        PROPS: "spring.datasource.url=jdbc:h2:mem:test\n",
        YAML: "spring:\n  datasource:\n    url: jdbc:postgresql://h/db\n",
    }

    assert detect_sql_dialect(_reader(files)) == "postgres"


def test_known_dialects() -> None:
    assert is_known_dialect("mysql")
    assert not is_known_dialect("not-a-database")


# --- effect on the runner ---------------------------------------------------------

MYSQL_MIGRATION = (
    "SELECT `id`, `status` FROM payment WHERE `status` = 'NEW';\n"
    "UPDATE payment AS p JOIN bulk_file AS s ON p.n = s.n SET p.t = s.t;\n"
)


def _run(dialect: str | None):  # type: ignore[no-untyped-def]
    return AnalysisRunner(dialect=dialect).run(
        repo="acme/x",
        pr_number=1,
        sources=[SourceFile(path="db/001.sql", content=MYSQL_MIGRATION)],
    )


def test_mysql_migration_is_unanalyzable_as_postgres() -> None:
    report = _run(None)

    assert report.degraded_stages == ["extract:db/001.sql"]


def test_the_same_migration_extracts_cleanly_as_mysql() -> None:
    report = _run("mysql")

    assert report.degraded_stages == []
    assert len(report.queries) == 2
    assert {query.dialect for query in report.queries} == {"mysql"}


def test_a_non_sql_source_is_left_alone() -> None:
    report = AnalysisRunner(dialect="mysql").run(
        repo="acme/x",
        pr_number=1,
        sources=[SourceFile(path="README.md", content="SELECT 1")],
    )

    assert report.queries == []


# --- end to end through cli.review ------------------------------------------------


def _with_files(recorded: RecordedPullRequest, files: dict[str, str]) -> RecordedGitHub:
    head_text = {**recorded.head_text, **files}
    return RecordedGitHub(recorded=dataclasses.replace(recorded, head_text=head_text))


def _entry(path: str) -> dict[str, object]:
    return {
        "filename": path,
        "status": "added",
        "patch": "@@ -0,0 +1,2 @@\n+x\n+y",
        "additions": 2,
        "deletions": 0,
        "changes": 2,
    }


def _mysql_pr(recorded: RecordedPullRequest, props: str) -> RecordedGitHub:
    head_text = {**recorded.head_text, "db/001.sql": MYSQL_MIGRATION, PROPS: props}
    pull = dataclasses.replace(recorded, entries=(_entry("db/001.sql"),), head_text=head_text)
    return RecordedGitHub(recorded=pull)


def test_review_detects_mysql_from_the_repos_own_config(recorded_pr: RecordedPullRequest) -> None:
    fake = _mysql_pr(recorded_pr, "spring.datasource.url=jdbc:mysql://h/db\n")

    result = cli.review(recorded_pr.repo, recorded_pr.number, client=fake.client, dry_run=True)

    assert not any(stage.startswith("extract:") for stage in result.report.degraded_stages)
    assert len(result.report.queries) == 2


def test_review_without_a_recognisable_url_keeps_the_default(
    recorded_pr: RecordedPullRequest,
) -> None:
    fake = _mysql_pr(recorded_pr, "spring.application.name=svc\n")

    result = cli.review(recorded_pr.repo, recorded_pr.number, client=fake.client, dry_run=True)

    assert "extract:db/001.sql" in result.report.degraded_stages


def test_the_override_beats_detection(recorded_pr: RecordedPullRequest) -> None:
    fake = _mysql_pr(recorded_pr, "spring.datasource.url=jdbc:postgresql://h/db\n")

    with override_settings(sql_dialect="mysql"):
        result = cli.review(recorded_pr.repo, recorded_pr.number, client=fake.client, dry_run=True)

    assert not any(stage.startswith("extract:") for stage in result.report.degraded_stages)


def test_a_typo_in_the_override_is_named_not_silently_ignored(
    recorded_pr: RecordedPullRequest,
) -> None:
    fake = _mysql_pr(recorded_pr, "spring.datasource.url=jdbc:mysql://h/db\n")

    with override_settings(sql_dialect="mysqll"):
        result = cli.review(recorded_pr.repo, recorded_pr.number, client=fake.client, dry_run=True)

    assert any(stage.startswith("sql_dialect:") for stage in result.report.degraded_stages)
