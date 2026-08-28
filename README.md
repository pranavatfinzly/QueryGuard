# QueryGuard

Catches slow and unsafe database queries in code review, before they reach production.

[![tests](https://img.shields.io/badge/tests-939%20passing-brightgreen)](#testing)
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
deterministic rules, reasons across the whole query set for N+1 access patterns no
single-query rule can see, and — as the plan-backed stages land — will run the
survivors against a real execution plan on an isolated reference database. It posts
its findings as a real GitHub Pull Request Review (`REQUEST_CHANGES` when something
blocking was found, `COMMENT` otherwise — QueryGuard never approves), so whether that
actually stops a merge is governed by the repository's own branch protection, the way
a human reviewer's review is.

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

- **Pull-request ingest & diff parsing** — read PR diffs via PyGithub, parse unified
  diff hunks, anchor findings to HEAD files with line offsets, handle added/modified/
  renamed/deleted files, skip unsupported languages, and degrade per-file gracefully.
- **SQL extraction** — every statement in a `.sql` file, migration, or snippet,
  parsed with `sqlglot`. Semicolons inside string literals and dollar-quoted function
  bodies are correctly not treated as boundaries.
- **`@Query` extraction** — Spring Data JPA annotations in Java classes and
  interfaces support JPQL plus native SQL with `nativeQuery = true`, including text
  blocks, while preserving source text and provenance. Matching runs against a
  scanned view of the file, so a query that exists only in a comment is not
  reported and a `default` method's braces do not truncate the interface.
- **Derived-method extraction** — `findBy`, `countBy`, `existsBy`, and `deleteBy`
  repository methods with equality predicates joined by `And` decode to a
  framework-neutral intermediate representation, then render to SQL-shaped
  semantic queries for static analysis.
- **Pluggable extraction** — one `Extractor` protocol and an extension registry, so
  a new source language is a new module plus one registration and no change to any
  stage downstream.
- **Accurate provenance** — every query carries `file:line`, resolved from token
  positions, so a finding anchors to the statement rather than the top of the file.
- **Five static rules** — unqualified writes, unbounded scans, unindexed filters,
  `SELECT *`, and non-sargable predicates. Each explains *what* it found, *why* it
  matters at scale, and *how* to fix it.
- **Automatic Liquibase schema discovery** — no `LIQUIBASE_CHANGELOG_PATH` needed for
  a standard Spring Boot repository: QueryGuard finds `db.liquibase.change-log` in
  `application.properties`/`.yml` on its own, and falls back to a repository-wide
  candidate search (scored by changelog topology, not filename guessing) before
  giving up. Schema-dependent rules stay silent, not wrong, when nothing is found.
  See [docs/liquibase-schema-discovery.md](docs/liquibase-schema-discovery.md).
- **Cross-file N+1 detection** — reads Java control flow (loops, repository call
  sites, cross-file type resolution) rather than query text, so it catches a
  repository call inside a loop or a lazy association dereferenced per row —
  patterns no single-query rule can see. Deterministic by construction: whether a
  pattern is reported never depends on an LLM. An optional provider (Groq today)
  may add explanatory prose, reconciled against the structural evidence before it
  can reach a finding, and corroborated against a captured p6spy statement log when
  one is available.
- **Deterministic, ranked findings** — worst severity first, stable across runs. The
  same input always produces byte-identical output.
- **A deterministic enforcement policy** — every run resolves to exactly one of
  `PASS` / `BLOCKED` / `DEGRADED` / `FAILED`, based purely on findings and stage
  health, never on prose. Blocking severities/rule IDs are configurable
  (`QUERYGUARD_BLOCK_SEVERITIES` etc.), defaulting to `CRITICAL,HIGH`.
- **A real GitHub Pull Request Review** — `REQUEST_CHANGES` when a blocking finding
  exists, `COMMENT` otherwise, **never `APPROVE`**. Idempotent via a hidden
  `<!-- queryguard:review -->` marker, so a re-run (a new push) edits or supersedes
  QueryGuard's own existing review instead of spamming the thread. QueryGuard never
  pushes commits, edits files, merges, or touches another actor's review — enforced
  structurally, not just by convention.
- **A CLI** (`queryguard review --repo OWNER/REPO --pr N`) — the entry point CI
  actually runs. `--post-comment` posts the review, `--dry-run` runs the full
  pipeline against a real PR without posting anything, `--fixture` runs fully
  offline against a recorded PR (no GitHub or LLM access at all), `--no-llm` skips
  LLM-authored prose even when it's configured. Exit codes distinguish a blocking
  finding (`2`) from QueryGuard failing to analyze reliably (`1`) from
  misconfiguration (`3`), for CI to key off directly.
- **A reusable GitHub Actions workflow** — any repository, public or private, adopts
  QueryGuard with a small workflow file that calls
  `queryguard-review.yml`; no local checkout, no vendoring, no shared service to
  stand up. See [docs/adopting-queryguard.md](docs/adopting-queryguard.md) for the
  setup, the branch-protection settings needed to make a blocking finding actually
  block a merge, and the one behavioral difference between public and private repos
  (fork pull requests).
- **HTTP API** — `GET /health` and `POST /analyze`, returning a fully typed report.
  `post_comment: true` posts the older plain-issue-comment form
  (`upsert_report_comment`), independent of the CLI's Pull Request Review path.
- **p6spy statement-log analysis** — parses a real statement log, normalizes literals
  via the AST, and isolates an N+1 by shape: 5,000 executions with 5,000 distinct bind
  values, where two queries would have done.
- **Markdown report rendering** — a pure function of the `Report` model, findings
  grouped by severity worst-first, degraded stages as explicit caveats above the
  findings, and snapshot-tested output.
- **Fail-soft everywhere** — one unreadable file, a failed LLM call, or an
  unreachable schema degrades to a named caveat while everything else is still
  analyzed in full. Never a 500, never a silently empty report, never a crash that
  hides a real finding behind a green check.
- **A sandbox with real bugs** — a Spring Boot fixture app carrying four planted
  performance bugs, each beside a healthy counterpart, so rules are tested for false
  positives as well as true ones.

### Coming soon

- **Execution plan analysis** — `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on an
  isolated Postgres 16 clone, inside `BEGIN` … `ROLLBACK`. This is the headline
  claim ("backed by a real execution plan") and the biggest remaining gap — nothing
  in a report is plan-backed yet.
- **Index simulation** — candidate indexes measured with HypoPG, with real
  before/after cost deltas.
- **Further Java / JPA extraction** — `EntityManager`/`Session` calls, named
  queries, and other unsupported annotation forms.
- **Further Spring Data derived methods** — operators, ordering, limits, distinct,
  nested properties, and collection semantics.
- **Four more static rules** — deep `OFFSET` paging, `IN` lists that should be joins,
  cartesian products, derived-method fan-out.
- **An org-wide installation model** — a GitHub App, so covering many repositories
  doesn't mean copying a workflow file into each one. Not required for "any repo,
  public or private" today — the reusable workflow already covers that — but the
  natural next step if QueryGuard ends up managing many repositories at once.

Only the listed available features are implemented; remaining milestones are not
silently approximated.

---

## Architecture

Extraction has one source-language boundary: `extract_source(source)` takes a
`SourceFile` and returns `list[ExtractedQuery]`, whatever language the file is
written in. A registry maps file extensions to extractors, so adding a language is
a new module and one registration — no stage downstream changes, and the
dispatcher names no language it routes to.

A linear pipeline; each stage consumes the previous stage's typed output. Every
contract is an immutable Pydantic model, so a stage cannot edit its input.

```
              Pull Request
                   │
                   ▼
   ●  1. Ingest             diff, base/head SHAs
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
   ●  7. N+1 Detection      cross-file structural analysis + optional LLM prose
                   │
                   ▼
   ●  8. Report             findings → ranked Markdown
                   │
                   ▼
   ●  9. Enforcement        PASS / BLOCKED / DEGRADED / FAILED, deterministic
                   │
                   ▼
        GitHub Pull Request Review   ●   REQUEST_CHANGES / COMMENT, never APPROVE
```

`●` implemented and tested  ·  `◐` partial — SQL and core Java/JPQL forms done, the
rest planned  ·  `○` entry point exists, raises `NotImplementedError`

Stages 1–3 and 7–9 are wired together end to end, driven by the CLI (`queryguard
review`) or, more narrowly, `POST /analyze`. Stages 4–6 are not wired, and the
pipeline does not pretend otherwise: it returns the report those stages would have
enriched, carrying only what the static and structural paths could establish.

Stage contracts, extension points, and the reasoning behind each boundary are
documented in [docs/architecture.md](docs/architecture.md).

### Design invariants

These hold for every stage, present and future:

1. **Never connect to a developer or production database.** Every run clones an
   isolated reference database from a schema snapshot.
2. **Every statement runs inside `BEGIN` … `ROLLBACK`.** Nothing QueryGuard executes
   can commit.
3. **QueryGuard's only write action is its own GitHub Pull Request Review** —
   `REQUEST_CHANGES` or `COMMENT`, never `APPROVE`. It never merges, pushes a
   commit, edits a file, creates or closes a pull request, or touches another
   actor's comment or review. Blocking a merge is a judgement GitHub's own review
   mechanism (via branch protection) enforces on QueryGuard's behalf, not something
   QueryGuard does directly.
4. **One review per PR, updated in place**, identified by a hidden marker.
5. **Fail soft.** A crashed stage degrades the report; it does not fail the check
   unless the enforcement policy says a real finding warrants it.

---

## Current Capabilities

What QueryGuard does today, end to end, against a real pull request, with no
Docker or JDK required:

| It can | Example |
| --- | --- |
| Split multi-statement SQL correctly | A `;` inside `'x;y'` or a `$$ … $$` body is not a boundary |
| Anchor findings to a line | `migrations/003_orders.sql:47`, not "somewhere in this file" |
| Flag an unqualified write as CRITICAL | `UPDATE customers SET tier = 'gold'` |
| Flag an unbounded table scan as HIGH | `SELECT * FROM orders` |
| Flag non-sargable predicates | `name LIKE '%smith'`, `LOWER(email) = ?`, `CAST(id AS TEXT) = '5'` |
| Flag a filter with no index behind it | Auto-discovers the Liquibase schema; silent without one, by design |
| Stay silent on healthy queries | `SELECT id, status FROM orders WHERE placed_at >= :since` → nothing |
| Catch a repository call inside a loop | Cross-file N+1, from control flow, not query text |
| Rank across files | A CRITICAL in the last file outranks a MEDIUM in the first |
| Degrade instead of failing | One unreadable file, schema, or LLM call is a named caveat |
| Post a real Pull Request Review | `REQUEST_CHANGES`/`COMMENT`, idempotent, never `APPROVE` |
| Decide PASS/BLOCKED/DEGRADED/FAILED | Deterministically, from findings and stage health alone |
| Refuse honestly | `diff` via the HTTP API returns **501**, never a falsely empty report |
| Isolate an N+1 from a statement log | 5,000 executions, 5,000 distinct binds → one group |

What it **cannot** do yet: execute anything against a database, produce an
`EXPLAIN` plan, or measure index impact with HypoPG.

---

## Roadmap

| Milestone | Scope |
| --- | --- |
| **1. Static analysis** ✅ | Rule engine, five rules, extraction, HTTP API, fail-soft pipeline |
| **2. First real PR review** ✅ | Markdown rendering, GitHub diff ingest, idempotent Pull Request Review, CLI |
| **3. Cross-query N+1** ✅ | Structural Java analysis, deterministic detection, optional Groq-authored prose |
| **4. Reusable adoption path** ✅ | Enforcement policy, `queryguard review` CLI, reusable GitHub Actions workflow |
| **5. Plan-backed findings** | Dockerized Postgres 16 + HypoPG, `EXPLAIN ANALYZE`, plan inspection, index simulation |
| **6. Java and JPA depth** | `EntityManager`/`Session` calls, named queries, richer Spring Data derived methods |
| **7. Org-wide installation** | GitHub App / webhook receiver, so adoption isn't one workflow file per repository |

---

## Project Structure

```
queryguard/
├── api/                     FastAPI surface
│   ├── main.py               /health, /analyze
│   └── deps.py                dependency injection
├── cli.py                   `queryguard review` — the entry point CI runs
├── policy.py                deterministic PASS/BLOCKED/DEGRADED/FAILED enforcement
├── fixtures.py               offline --fixture support for the CLI
├── config.py                 the only module that reads the environment
├── pipeline/                 one module per stage, in run order
│   ├── runner.py              orchestration + fail-soft boundaries
│   ├── diff.py / ingest.py    PR event → run context + diff
│   ├── extract/                base.py · registry.py · dispatcher.py
│   │                           sql.py · java.py · java_source.py
│   │                           java_structure.py · derived.py
│   ├── static_rules/           engine, registry, schema context, rules/
│   ├── nplusone.py             cross-file N+1 detection
│   ├── explain.py               EXPLAIN ANALYZE + plan parsing (not yet wired)
│   ├── hypopg.py                candidate indexes + cost deltas (not yet wired)
│   └── report.py               findings → ranked Markdown
├── db/                       reference DB lifecycle, rollback-only sessions
│   ├── discovery.py            Liquibase changelog auto-discovery
│   ├── candidate_discovery.py  repository-wide changelog fallback search
│   ├── liquibase.py            changelog → table schema
│   ├── provision.py            Postgres + HypoPG lifecycle (not yet wired)
│   └── session.py                BEGIN/ROLLBACK helpers (not yet wired)
├── integrations/              github.py · groq.py · llm.py · claude.py (stub) · p6spy.py
└── models/                    Pydantic contracts between stages

queryguard-sandbox/           Spring Boot fixture app with four planted bugs
.github/workflows/
├── queryguard-review.yml     reusable workflow — what a consumer repo calls
└── queryguard.yml            this repo's own dogfooding trigger
docs/
├── adopting-queryguard.md    how another repository adopts QueryGuard
├── architecture.md           stage contracts and extension points
└── liquibase-schema-discovery.md
tests/
├── unit/                     939 tests — no Docker, JDK, or credentials
└── fixtures/                 captured p6spy logs, recorded PR diffs, report snapshots
```

---

## Quick Start

**Requirements:** Python 3.11+. No Docker or JDK needed for anything below.

```bash
git clone https://github.com/pranavatfinzly/QueryGuard.git
cd QueryGuard
pip install -r requirements.txt
```

Run the tests:

```bash
pytest                                    # 939 passed
pytest tests/unit/static_rules/ -v        # just the rule suites
```

### Review a real pull request from the command line

```bash
export GITHUB_TOKEN=ghp_...                       # read access is enough for --dry-run
queryguard review --repo OWNER/REPO --pr 42 --dry-run
```

Drop `--dry-run` (and grant the token pull-request write access) to have it
actually post its review. See [docs/adopting-queryguard.md](docs/adopting-queryguard.md)
for wiring this into CI so it runs automatically on every pull request, in your
own repository or any other.

### Start the HTTP API

```bash
uvicorn queryguard.api.main:app --reload
```

Interactive docs are then at `http://localhost:8000/docs`.

### Use it as a library

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

Analyze several named files in one call with `sql_files` (SQL, optionally with a
`dialect`) or `sources` (any language the extract stage routes by extension, such
as `.java`). If one cannot be parsed, the others are still analyzed and the
response reports `status: "degraded"` with `degraded_stages: ["extract:<path>"]` —
HTTP 200, never a 500.

`diff` is accepted by the schema but returns **501**: answering "no
problems found" to input that was never read is the one failure mode a review bot
cannot have. `post_comment: true` posts an idempotent plain comment on the PR —
the CLI's `--post-comment` (below) is the path that posts a real Pull Request
Review, and is what CI actually uses.

---

## Testing

**939 tests. All passing. Under 10 seconds. No Docker, JDK, credentials, or network.**

```bash
pytest                                                  # everything
pytest tests/unit/static_rules/ -v                      # the rule suites
pytest tests/unit/test_sql_extraction.py -v             # SQL extraction
pytest tests/unit/test_java_source.py -v                # the Java scanner
pytest tests/unit/nplusone/ -v                          # cross-file N+1 detection
pytest tests/unit/test_policy.py -v                      # enforcement policy
pytest tests/unit/test_github_review.py -v               # Pull Request Review posting
pytest tests/unit/test_cli.py -v                          # the `queryguard review` CLI
```

Every rule ships with a false-positive guard as well as a positive case — usually the
sandbox's healthy counterpart to the bug being caught, because a review bot that cries
wolf gets muted. Beyond the per-rule suites, the pipeline is tested for determinism
(the same diff must not produce two different reviews), lossless JSON round-tripping,
internal consistency (every finding points at a query in the same report, at the line
that query came from), and concurrency safety under a shared runner.

Tests that need Docker will live behind the `integration` marker declared in
`pytest.ini`. None exist yet — the stages that would need one (provisioning,
`EXPLAIN`, HypoPG) are not wired in yet either.

---

## Current Status

**Early development.** The static analysis, cross-file N+1 detection, deterministic
enforcement policy, and GitHub Pull Request Review posting are real, tested, and
usable today — this is a working PR bot, not a prototype of one, for the queries a
diff's text and control flow can prove something about. What is not yet real is the
plan-backed half the project is ultimately built around: no `EXPLAIN` plan is ever
produced, and no index impact is ever measured, because Postgres provisioning and
HypoPG simulation are not wired in. Their entry points exist and raise
`NotImplementedError` rather than a plausible-looking placeholder result.

Use it today as a deterministic SQL/JPA static-analysis PR bot with real
cross-query N+1 detection — not yet as a source of plan-verified findings.

Engineering detail — per-stage status and technical debt — is tracked in
[STATUS.md](STATUS.md), though it lags behind this README at times; where they
disagree, trust the code and this README over it.

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
- **Stage contracts are immutable.** Models derive from `models.base.Contract`;
  derive a changed value with `model_copy(update=...)` rather than assigning.

**Adding a source language:**

1. Add a module under `queryguard/pipeline/extract/` exposing a class with
   `extract(source: SourceFile) -> list[ExtractedQuery]`.
2. Register it: `_EXTRACTORS.register(".ext", YourExtractor())` in
   `extract/dispatcher.py`, or `register_extractor(...)` from outside the package.
3. Nothing else changes — no stage downstream knows which language a query came
   from.

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
