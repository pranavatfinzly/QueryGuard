# QueryGuard

Catches slow and unsafe database queries in code review, before they reach production.

[![tests](https://img.shields.io/badge/tests-227%20passing-brightgreen)](#testing)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](#quick-start)
[![typed](https://img.shields.io/badge/mypy-strict-blue)](#contributing)
[![status](https://img.shields.io/badge/status-early%20development-orange)](#current-status)

---

## Why QueryGuard?

**The problem.** A slow query almost never looks slow. `SELECT * FROM orders` passes
code review because at review time `orders` has 400 rows. `findByCustomerId` called
inside a `for` loop reads as ordinary Java — each execution is genuinely fast, and
only the five-thousandth repetition is the defect. A `WHERE country = ?` predicate
looks indexed until you check the migration and find it isn't. None of these are
visible in a diff, so they ship, and they surface months later as a pager alert with
no obvious cause.

**The solution.** QueryGuard reviews the queries in a pull request the way a database
specialist would: it extracts every query the diff touches, checks each against
deterministic rules, and — as those stages land — runs the survivors against a real
execution plan on an isolated reference database, then posts one comment explaining
what it found, why it matters at scale, and how to fix it.

**Why execution plans matter.** Static analysis can tell you a query has no `WHERE`
clause. It cannot tell you whether `WHERE status = 'active'` will use an index,
because the answer depends on the schema, the statistics, and the planner — not the
SQL text. Only the plan knows that the predicate resolves to a sequential scan over
2 million rows, that the row estimate is off by 400×, or that the sort spilled to
disk. And only a *simulated* index (via HypoPG) can tell you that adding one would
cut the cost by 90% — before anyone commits to building it.

This is why QueryGuard is built around a real database rather than a linter. It is
also why the plan-backed half of it is still under construction: getting there
honestly is more work than pattern-matching SQL, and the project reports exactly
which half you get today.

---

## Features

### Available now

- **SQL extraction** — every statement in a `.sql` file, migration, or snippet,
  parsed with `sqlglot`. Semicolons inside string literals and dollar-quoted function
  bodies are correctly not treated as boundaries.
- **JPQL `@Query` extraction** — simple Spring Data JPA annotations in Java classes
  and interfaces, including text blocks, preserve their source text and provenance.
- **Accurate provenance** — every query carries `file:line`, resolved from token
  positions, so a finding anchors to the statement rather than the top of the file.
- **Five static rules** — unqualified writes, unbounded scans, unindexed filters,
  `SELECT *`, and non-sargable predicates. Each explains *what* it found, *why* it
  matters at scale, and *how* to fix it.
- **Deterministic, ranked findings** — worst severity first, stable across runs. The
  same input always produces byte-identical output.
- **Extensible rule engine** — one file per rule, registered at import, parsed once
  per query, with per-rule failure isolation.
- **Fail-soft everywhere** — one unreadable file degrades to a named caveat while
  every other file is still analyzed in full. Never a 500, never a silently empty
  report.
- **HTTP API** — `GET /health` and `POST /analyze`, returning a fully typed report.
- **p6spy statement-log analysis** — parses a real statement log, normalizes literals
  via the AST, and isolates an N+1 by shape: 5,000 executions with 5,000 distinct bind
  values, where two queries would have done.
- **A sandbox with real bugs** — a Spring Boot fixture app carrying four planted
  performance bugs, each beside a healthy counterpart, so rules are tested for false
  positives as well as true ones.

### Coming soon

- **Pull-request ingest** — read the diff from GitHub instead of being handed SQL.
- **Further Java / JPA extraction** — native queries, `EntityManager` and `Session`
  calls, named queries, and other unsupported annotation forms.
- **Spring Data derived methods** — decoding `findByCustomerIdAndStatusOrderBy…` into
  the query it actually emits.
- **Execution plan analysis** — `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on an
  isolated Postgres 16 clone, inside `BEGIN` … `ROLLBACK`.
- **Index simulation** — candidate indexes measured with HypoPG, with real
  before/after cost deltas.
- **N+1 detection** — cross-query reasoning powered by Claude, corroborated by p6spy
  statement counts.
- **Markdown reports and one idempotent PR comment** — tagged, updated in place, never
  spamming the thread.
- **Four more static rules** — deep `OFFSET` paging, `IN` lists that should be joins,
  cartesian products, derived-method fan-out.

Only the listed available features are implemented; remaining milestones are not
silently approximated.

---

## Architecture

Extraction has one source-language boundary: `extract_queries(path, content)`. It
routes `.sql` files to the SQL extractor and `.java` files to narrow JPQL `@Query`
extraction.
every route returns `list[ExtractedQuery]`, so analysis does not depend on the source
language.

A linear pipeline; each stage consumes the previous stage's typed output.

```
              Pull Request
                   │
                   ▼
   ○  1. Ingest             diff, base/head SHAs
                   │
                   ▼
   ◐  2. Extraction         query text + file:line provenance
                   │
                   ▼
   ●  3. Static Analysis    deterministic rules over parsed ASTs
                   │
                   ▼
   ○  4. Provision          isolated Postgres 16 + HypoPG
                   │
                   ▼
   ○  5. Execution Plan     EXPLAIN ANALYZE inside BEGIN/ROLLBACK
                   │
                   ▼
   ○  6. HypoPG             simulated indexes, before/after cost
                   │
                   ▼
   ○  7. AI Explanation     N+1 patterns across the query set
                   │
                   ▼
   ○  8. Report             findings → ranked Markdown
                   │
                   ▼
             GitHub Comment  ○  one comment, updated in place
```

`●` implemented and tested  ·  `◐` partial — SQL done, Java/JPQL planned  ·  `○` entry
point exists, raises `NotImplementedError`

Stages 2 and 3 are wired together behind `POST /analyze` by an orchestrator that owns
stage order and fail-soft boundaries. Stages 4–8 are not wired, and the pipeline does
not pretend otherwise: it returns the report those stages would have enriched,
carrying only what the static path could establish.

### Design invariants

These hold for every stage, present and future:

1. **Never connect to a developer or production database.** Every run clones an
   isolated reference database from a schema snapshot.
2. **Every statement runs inside `BEGIN` … `ROLLBACK`.** Nothing QueryGuard executes
   can commit.
3. **Read-only with respect to the PR.** QueryGuard comments. It never pushes commits,
   edits files, or approves or blocks a merge.
4. **One comment per PR, updated in place**, identified by a hidden marker.
5. **Fail soft.** A crashed stage degrades the report; it does not fail the check.

---

## Current Capabilities

What QueryGuard does today, end to end, with no Docker, JDK, or credentials:

| It can | Example |
| --- | --- |
| Split multi-statement SQL correctly | A `;` inside `'x;y'` or a `$$ … $$` body is not a boundary |
| Anchor findings to a line | `migrations/003_orders.sql:47`, not "somewhere in this file" |
| Flag an unqualified write as CRITICAL | `UPDATE customers SET tier = 'gold'` |
| Flag an unbounded table scan as HIGH | `SELECT * FROM orders` |
| Flag non-sargable predicates | `name LIKE '%smith'`, `LOWER(email) = ?`, `CAST(id AS TEXT) = '5'` |
| Flag a filter with no index behind it | Needs schema context; silent without it, by design |
| Stay silent on healthy queries | `SELECT id, status FROM orders WHERE placed_at >= :since` → nothing |
| Rank across files | A CRITICAL in the last file outranks a MEDIUM in the first |
| Degrade instead of failing | One unparseable file is a named caveat; the rest are analyzed |
| Refuse honestly | `diff` and `post_comment` return **501**, never a falsely empty report |
| Isolate an N+1 from a statement log | 5,000 executions, 5,000 distinct binds → one group |

What it **cannot** do yet: read a pull request, execute anything against a database,
produce an `EXPLAIN` plan, measure index impact, detect N+1 patterns from source,
render Markdown, or post a comment.

---

## Roadmap

| Milestone | Scope |
| --- | --- |
| **1. Static analysis** ✅ | Rule engine, five rules, extraction, HTTP API, fail-soft pipeline |
| **2. First real PR comment** | Markdown rendering, GitHub diff ingest, one idempotent tagged comment, CLI |
| **3. Plan-backed findings** | Dockerized Postgres 16 + HypoPG, `EXPLAIN ANALYZE`, plan inspection, index simulation |
| **4. Java and JPA** | JavaParser sidecar, `@Query`, JPQL/HQL, Spring Data derived methods |
| **5. AI cross-query analysis** | Claude-powered N+1 detection, corroborated by p6spy statement counts |
| **6. Production hardening** | Webhook routes with signature verification, CI workflows, reusable GitHub Action |

---

## Project Structure

```
queryguard/
├── api/                  FastAPI surface
│   ├── main.py           /health, /analyze
│   └── deps.py           dependency injection
├── pipeline/             one module per stage, in run order
│   ├── runner.py         orchestration + fail-soft boundaries
│   ├── ingest.py         PR event → run context + diff
│   ├── extract/          sql.py · java.py · derived.py
│   ├── static_rules/     engine, registry, schema context, rules/
│   ├── explain.py        EXPLAIN ANALYZE + plan parsing
│   ├── hypopg.py         candidate indexes + cost deltas
│   ├── nplusone.py       cross-query analysis
│   └── report.py         findings → ranked Markdown
├── db/                   reference DB lifecycle, rollback-only sessions
├── integrations/         github.py · claude.py · p6spy.py
└── models/               Pydantic contracts between stages

queryguard-sandbox/       Spring Boot fixture app with four planted bugs
tests/
├── unit/                 227 tests — no Docker, JDK, or credentials
└── fixtures/             captured p6spy statement logs
```

---

## Quick Start

**Requirements:** Python 3.11+. Nothing else — no Docker, no JDK, no API keys.

```bash
git clone https://github.com/pranavatfinzly/QueryGuard.git
cd QueryGuard
pip install -r requirements.txt
```

Run the tests:

```bash
pytest                                    # 227 passed
pytest tests/unit/static_rules/ -v        # just the rule suites
```

Start the API:

```bash
uvicorn queryguard.api.main:app --reload
```

Interactive docs are then at `http://localhost:8000/docs`.

Use it as a library:

```python
from queryguard.models import SqlSource
from queryguard.pipeline.runner import AnalysisRunner

report = AnalysisRunner().run(
    repo="acme/billing-service",
    pr_number=42,
    sources=[SqlSource(path="migrations/003_orders.sql", content="SELECT * FROM orders")],
)

for finding in report.findings:
    print(f"{finding.severity.value:8} {finding.rule_id:16} {finding.title}")
```

```
high     no-limit         SELECT reads an entire table with no row limit
medium   select-star      Query selects every column with `SELECT *`
```

---

## Example API Request

```bash
curl -s localhost:8000/analyze \
  -H 'content-type: application/json' \
  -d '{
    "repo": "acme/billing-service",
    "pr_number": 42,
    "sql": "SELECT * FROM orders;"
  }'
```

### Response

```json
{
  "run_id": "2c8ba92a-d05e-4c37-a187-915247d6270c",
  "status": "completed",
  "report": {
    "context": {
      "run_id": "2c8ba92a-d05e-4c37-a187-915247d6270c",
      "repo": "acme/billing-service",
      "pr_number": 42
    },
    "queries": [
      {
        "id": "inline.sql:1", "kind": "raw_sql", "text": "SELECT * FROM orders",
        "dialect": "postgres", "parse_error": null,
        "provenance": { "file": "inline.sql", "line": 1 }
      }
    ],
    "findings": [
      {
        "rule_id": "no-limit",
        "severity": "high",
        "title": "SELECT reads an entire table with no row limit",
        "explanation": "This SELECT reads `orders` with no WHERE clause and no LIMIT/FETCH, so the result set is the whole table.",
        "impact": "Cost is proportional to table size with no ceiling, so the query passes review at today's row count and degrades continuously as the table grows...",
        "provenance": { "file": "inline.sql", "line": 1 },
        "query_id": "inline.sql:1",
        "suggestions": [
          {
            "description": "Decide what bounds this query and say it in SQL: a WHERE clause if the caller wants a subset, keyset pagination, or a server-side cursor..."
          }
        ]
      },
      {
        "rule_id": "select-star",
        "severity": "medium",
        "title": "Query selects every column with `SELECT *`",
        "explanation": "The projection is `*`, so the query returns every column of every row it matches...",
        "provenance": { "file": "inline.sql", "line": 1 },
        "query_id": "inline.sql:1"
      }
    ],
    "degraded_stages": []
  }
}
```

Analyze several named files in one call with `sql_files`. If one cannot be parsed, the
others are still analyzed and the response reports `status: "degraded"` with
`degraded_stages: ["extract:<path>"]` — HTTP 200, never a 500.

`diff` and `post_comment` are accepted by the schema but return **501**: answering "no
problems found" to input that was never read is the one failure mode a review bot
cannot have.

---

## Testing

**227 tests. All passing. Under a second. No Docker, JDK, credentials, or network.**

```bash
pytest                                                  # everything
pytest tests/unit/static_rules/ -v                      # the rule suites (92)
pytest tests/unit/test_sql_extraction.py -v             # extraction (36)
pytest tests/unit/test_analyze_endpoint.py -v           # the HTTP surface (16)
```

Every rule ships with a false-positive guard as well as a positive case — usually the
sandbox's healthy counterpart to the bug being caught, because a review bot that cries
wolf gets muted. Beyond the per-rule suites, the pipeline is tested for determinism
(the same diff must not produce two different comments), lossless JSON round-tripping,
internal consistency (every finding points at a query in the same report, at the line
that query came from), and concurrency safety under a shared runner.

Tests that need Docker will live behind the `integration` marker declared in
`pytest.ini`. None exist yet.

---

## Current Status

**Early development — roughly 30% complete.** QueryGuard today performs
production-quality SQL extraction and static analysis behind a working HTTP API, with
a deterministic, fail-soft pipeline and 227 passing tests. Execution-plan analysis,
HypoPG index simulation, GitHub integration, Java/JPA extraction, AI-powered N+1
detection, and Markdown reporting are all under active development — their entry
points exist and raise `NotImplementedError`, and the API refuses requests that would
depend on them rather than returning an empty report. Use it today as a SQL analysis
library or a local service; it is not yet a working PR bot.

Engineering detail — per-stage status, technical debt, test breakdown, and the next
milestone's acceptance criteria — is tracked in [STATUS.md](STATUS.md).

---

## Contributing

Contributions are welcome. Read [CLAUDE.md](CLAUDE.md) first — it holds the pipeline
design, the folder layout, and the conventions this codebase is held to.

**Conventions in brief:**

- **Type hints everywhere**, checked by `mypy --strict`. A new `Any` needs a comment
  justifying it.
- **Pydantic models are the stage contracts.** Stages exchange models from
  `queryguard/models/`, never bare dicts or tuples.
- **Parse SQL with `sqlglot`; never regex it.** If `sqlglot` cannot parse a candidate,
  record it as unanalyzable rather than guessing.
- **No bare `except`.** Catch the specific exception; where a stage must fail soft,
  catch at the stage boundary, log with the run ID, and return a degraded result.
- **Formatting and linting:** `ruff format` and `ruff check`, line length 100.

**Adding a static rule:**

1. Add one file under `queryguard/pipeline/static_rules/rules/`, named after the smell
   it detects, exposing a class with a `rule_id` and a `check(context)` method, and
   calling `register()` at module scope.
2. Import it in `static_rules/__init__.py` — registration is an import side effect, so
   an unimported rule silently never runs.
3. Add its ID to the registry assertion in `tests/unit/test_placeholders.py`.
4. Ship a test suite with **at least one query it must flag and one similar query it
   must not**. Prefer the sandbox's planted bugs and their healthy counterparts over
   hand-written SQL.

**Before opening a pull request:** `ruff format . && ruff check . && mypy && pytest`

Do not weaken the five design invariants above for convenience, and do not mark
unfinished work as complete in the documentation — `tests/unit/test_placeholders.py`
asserts that unimplemented stages stay unimplemented, and that is deliberate.

---

## License

No license has been declared for this repository yet.
