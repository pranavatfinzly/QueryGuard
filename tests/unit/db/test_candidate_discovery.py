"""Repository-wide Liquibase changelog candidate search — unit level.

Exercises :func:`find_changelog_candidates` and :func:`resolve_candidate_discovery`
directly against an in-memory ``read``, the same seam
``tests/unit/db/test_discovery.py`` uses for the conventional-location
discovery this module falls back from.
"""

from __future__ import annotations

from queryguard.db.candidate_discovery import (
    CandidateConfidence,
    find_changelog_candidates,
    resolve_candidate_discovery,
)
from queryguard.db.discovery import DiscoveryStatus
from queryguard.db.liquibase import ReadChangelogFile

_NS = 'xmlns="http://www.liquibase.org/xml/ns/dbchangelog"'


def _changelog(*, changesets: int = 0, includes: tuple[str, ...] = ()) -> str:
    body = "".join(
        f'<changeSet id="{i}" author="t"><createTable tableName="t"/></changeSet>'
        for i in range(changesets)
    )
    body += "".join(f'<include file="{name}" relativeToChangelogFile="true"/>' for name in includes)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<databaseChangeLog {_NS}>{body}</databaseChangeLog>\n'


def _reader(files: dict[str, str]) -> ReadChangelogFile:
    def read(path: str) -> str:
        if path not in files:
            raise LookupError(path)
        return files[path]

    return read


# --- find_changelog_candidates: what counts as a candidate at all -----------------


def test_a_non_xml_path_is_never_read() -> None:
    read = _reader({})
    candidates = find_changelog_candidates(["README.md", "src/App.java"], read)

    assert candidates == []


def test_an_xml_file_that_is_not_liquibase_shaped_is_not_a_candidate() -> None:
    read = _reader(
        {"pom.xml": "<?xml version='1.0'?><project><artifactId>x</artifactId></project>"}
    )

    assert find_changelog_candidates(["pom.xml"], read) == []


def test_malformed_xml_is_not_a_candidate() -> None:
    read = _reader({"db/changelog.xml": "<databaseChangeLog><unclosed>"})

    assert find_changelog_candidates(["db/changelog.xml"], read) == []


def test_an_unreadable_path_is_not_a_candidate_not_an_error() -> None:
    read = _reader({})  # every read raises LookupError

    assert find_changelog_candidates(["db/changelog.xml"], read) == []


def test_a_valid_but_bare_databasechangelog_is_low_confidence() -> None:
    read = _reader({"random/thing.xml": _changelog()})

    (candidate,) = find_changelog_candidates(["random/thing.xml"], read)

    assert candidate.confidence is CandidateConfidence.LOW
    assert "valid databaseChangeLog root element" in candidate.reasons


# --- Scoring: referenced-by-another-candidate is the strongest signal -------------


def test_a_candidate_referenced_by_another_valid_changelog_is_medium() -> None:
    read = _reader(
        {
            "db/root.xml": _changelog(includes=("child.xml",)),
            "db/child.xml": _changelog(changesets=1),
        }
    )

    candidates = find_changelog_candidates(["db/root.xml", "db/child.xml"], read)
    by_path = {c.path: c for c in candidates}

    assert by_path["db/child.xml"].confidence is CandidateConfidence.MEDIUM
    assert "referenced by another candidate's <include>" in by_path["db/child.xml"].reasons


def test_content_plus_naming_convention_together_are_medium_but_neither_alone_is() -> None:
    # Content without a conventional name: LOW.
    content_only = _reader({"random/thing.xml": _changelog(changesets=1)})
    (candidate,) = find_changelog_candidates(["random/thing.xml"], content_only)
    assert candidate.confidence is CandidateConfidence.LOW

    # A conventional name with no content and nothing referencing it: LOW.
    naming_only = _reader({"db/changelog/master.xml": _changelog()})
    (candidate,) = find_changelog_candidates(["db/changelog/master.xml"], naming_only)
    assert candidate.confidence is CandidateConfidence.LOW

    # Both together: MEDIUM.
    both = _reader({"db/changelog/master.xml": _changelog(changesets=1)})
    (candidate,) = find_changelog_candidates(["db/changelog/master.xml"], both)
    assert candidate.confidence is CandidateConfidence.MEDIUM


def test_candidates_are_capped_at_the_configured_limit() -> None:
    files = {f"f{i}.xml": _changelog() for i in range(10)}
    read = _reader(files)

    candidates = find_changelog_candidates(list(files), read, limit=3)

    assert len(candidates) == 3


# --- resolve_candidate_discovery: the DiscoveryResult-shaped outcome --------------


def test_no_candidates_anywhere_is_not_found() -> None:
    result = resolve_candidate_discovery(["README.md"], _reader({}))

    assert result.status is DiscoveryStatus.NOT_FOUND
    assert result.changelog_path is None


def test_one_unambiguous_medium_candidate_is_discovered() -> None:
    read = _reader(
        {
            "db/root.xml": _changelog(includes=("child.xml",)),
            "db/child.xml": _changelog(changesets=1),
            "unrelated/notes.xml": _changelog(),  # LOW — never referenced, no convention
        }
    )

    result = resolve_candidate_discovery(
        ["db/root.xml", "db/child.xml", "unrelated/notes.xml"], read
    )

    assert result.status is DiscoveryStatus.DISCOVERED
    assert result.changelog_path == "db/child.xml"
    assert result.source_file is not None
    assert "repository fallback" in result.source_file


def test_two_equally_plausible_candidates_are_ambiguous_not_guessed() -> None:
    read = _reader(
        {
            "service-a/db/changelog/master.xml": _changelog(changesets=1),
            "service-b/db/changelog/master.xml": _changelog(changesets=1),
        }
    )

    result = resolve_candidate_discovery(
        ["service-a/db/changelog/master.xml", "service-b/db/changelog/master.xml"], read
    )

    assert result.status is DiscoveryStatus.AMBIGUOUS
    assert result.changelog_path is None
    assert result.reason is not None
    assert "service-a/db/changelog/master.xml" in result.reason
    assert "service-b/db/changelog/master.xml" in result.reason


def test_a_medium_candidate_wins_over_a_low_one_not_ambiguous() -> None:
    # A referenced MEDIUM candidate alongside an unrelated LOW one is not a
    # tie — only candidates at the *best* tier compete for ambiguity.
    read = _reader(
        {
            "db/root.xml": _changelog(includes=("child.xml",)),
            "db/child.xml": _changelog(changesets=1),
            "docs/example-changelog.xml": _changelog(),  # LOW: naming hint alone
        }
    )

    result = resolve_candidate_discovery(
        ["db/root.xml", "db/child.xml", "docs/example-changelog.xml"], read
    )

    assert result.status is DiscoveryStatus.DISCOVERED
    assert result.changelog_path == "db/child.xml"
