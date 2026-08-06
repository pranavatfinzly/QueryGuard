"""Dependency providers for the API layer.

Routes declare what they need with ``Depends`` instead of importing it, which is
what makes the pipeline swappable at the edge: a test overrides
:func:`get_analysis_runner` through ``app.dependency_overrides`` to inject a runner
with a narrower rule set, a fixed run ID, or a deliberate failure, without patching
module globals.

Clients, settings, and database handles land here as the stages that need them are
implemented.
"""

from __future__ import annotations

from functools import lru_cache

from queryguard.pipeline.runner import AnalysisRunner

__all__ = ["get_analysis_runner"]


@lru_cache(maxsize=1)
def get_analysis_runner() -> AnalysisRunner:
    """The process-wide analysis runner.

    Cached rather than built per request: the runner holds no per-run state, and
    constructing one builds a rule engine and installs sqlglot's log filter, neither
    of which should repeat on every request.
    """
    return AnalysisRunner()
