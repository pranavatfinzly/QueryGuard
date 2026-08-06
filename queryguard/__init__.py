"""QueryGuard — reviews database queries for performance problems before they merge.

Package layout mirrors the pipeline described in CLAUDE.md:

- :mod:`queryguard.api` — FastAPI surface
- :mod:`queryguard.pipeline` — one module per stage, in run order
- :mod:`queryguard.db` — isolated reference database, rollback-only sessions
- :mod:`queryguard.integrations` — GitHub, Claude, p6spy
- :mod:`queryguard.models` — the typed contracts between stages
"""

__version__ = "0.1.0"
