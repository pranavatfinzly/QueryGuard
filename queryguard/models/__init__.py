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
from queryguard.models.java_structure import (
    ArgumentDependency,
    EntityRelationship,
    InjectionKind,
    IterationContext,
    IterationKind,
    JavaFileStructure,
    JavaProgram,
    LazyAssociationAccess,
    RepositoryCallSite,
    RepositoryDeclaration,
    RepositoryResolution,
    SourceSpan,
)
from queryguard.models.nplusone import (
    EvidenceTier,
    NPlusOneCandidate,
    NPlusOneExplanation,
    NPlusOneKind,
    RuntimeCorroboration,
)
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
    "ArgumentDependency",
    "ChangeStatus",
    "ChangedFile",
    "Contract",
    "DiffIngest",
    "EntityRelationship",
    "Evidence",
    "EvidenceTier",
    "ExtractedQuery",
    "Finding",
    "Hunk",
    "InjectionKind",
    "IterationContext",
    "IterationKind",
    "JavaFileStructure",
    "JavaProgram",
    "LazyAssociationAccess",
    "NPlusOneCandidate",
    "NPlusOneExplanation",
    "NPlusOneKind",
    "Provenance",
    "QueryKind",
    "Report",
    "RepositoryCallSite",
    "RepositoryDeclaration",
    "RepositoryResolution",
    "RunContext",
    "RuntimeCorroboration",
    "Severity",
    "SkipReason",
    "SkippedFile",
    "SourceFile",
    "SourceSpan",
    "SqlSource",
    "Suggestion",
]
