"""Typed contracts exchanged between pipeline stages.

Stages pass these models to each other — never bare dicts or tuples. Adding a
field to a stage's output means adding it here first.

Re-exported at package level so callers can write ``from queryguard.models import
Finding`` without caring which module a model happens to live in; the split into
``query`` / ``finding`` / ``report`` is for authoring, not for consumers.
"""

from __future__ import annotations

from queryguard.models.finding import Evidence, Finding, Severity, Suggestion
from queryguard.models.query import ExtractedQuery, Provenance, QueryKind
from queryguard.models.report import Report, RunContext

__all__ = [
    "Evidence",
    "ExtractedQuery",
    "Finding",
    "Provenance",
    "QueryKind",
    "Report",
    "RunContext",
    "Severity",
    "Suggestion",
]
