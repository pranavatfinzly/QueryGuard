"""Typed contracts exchanged between pipeline stages.

Stages pass these models to each other — never bare dicts or tuples. Adding a
field to a stage's output means adding it here first.

Re-exported at package level so callers can write ``from queryguard.models import
Finding`` without caring which module a model happens to live in; the split into
``query`` / ``finding`` / ``report`` is for authoring, not for consumers.
"""

from __future__ import annotations

from queryguard.models.base import Contract
from queryguard.models.diff import (
    ChangedFile,
    ChangeStatus,
    DiffIngest,
    SkippedFile,
    SkipReason,
)
from queryguard.models.finding import Evidence, Finding, Severity, Suggestion
from queryguard.models.query import (
    ExtractedQuery,
    Hunk,
    Provenance,
    QueryKind,
    SourceFile,
    SqlSource,
)
from queryguard.models.report import Report, RunContext

__all__ = [
    "ChangeStatus",
    "ChangedFile",
    "Contract",
    "DiffIngest",
    "Evidence",
    "ExtractedQuery",
    "Finding",
    "Hunk",
    "Provenance",
    "QueryKind",
    "Report",
    "RunContext",
    "Severity",
    "SkipReason",
    "SkippedFile",
    "SourceFile",
    "SqlSource",
    "Suggestion",
]
