"""Stage 3 — Static analysis.

Planned rules: ``SELECT *``, missing ``WHERE``, leading-wildcard ``LIKE``,
functions wrapping indexed columns, implicit casts, unbounded result sets,
``OFFSET``-based deep paging, ``IN`` lists that should be joins, cartesian
products, and derived-method patterns that fan out.

Importing this package is what puts rules in the registry: each module under
:mod:`.rules` calls :func:`register` at import time, so it must be imported here
to take effect.
"""

from __future__ import annotations

from queryguard.pipeline.static_rules.base import (
    RULES,
    Rule,
    register,
    run_static_rules,
)

__all__ = ["RULES", "Rule", "register", "run_static_rules"]
