# QueryGuard

It catches slow and unsafe database queries before they merge. It runs on every pull request,
analyzes SQL, JPA native queries, JPQL/HQL, and Spring Data derived methods against a real execution
plan, and posts a clear explanation with a suggested fix which is backed by measured index impact via HypoPG
and cross-query N+1 detection powered by Claude.

> **Status: one of eight stages done, one partial.** Static analysis (stage 3) is
> implemented and tested. Extraction (stage 2) is implemented for SQL only — the Java and
> derived-method halves are still stubs, as is the dispatcher that routes a diff to either.
> p6spy statement-log parsing is implemented, but it is a supporting integration for the
> N+1 stage rather than a stage itself. Six stages raise `NotImplementedError`
> (16 stub entry points), nothing reaches a database yet, and `POST /analyze` still returns
> an empty report with `status: "not_implemented"` because no stage is wired into it.
> **150 unit tests pass**, needing no Docker, JDK, or credentials.

## What works today

| Area | State |
| --- | --- |
| **Static analysis** (`pipeline/static_rules/`) | **Implemented.** Five rules, a rule engine, and a schema-context provider. See below. |
| **SQL extraction** (`pipeline/extract/sql.py`) | **Implemented.** Splits statements on tokenized semicolons (not `str.split(";")`, which breaks on a semicolon inside a string literal), preserves each statement verbatim, and resolves real line numbers for provenance. |
| **p6spy log parsing** (`integrations/p6spy.py`) | **Implemented.** Normalizes literals out of SQL via the sqlglot AST, groups by statement shape, ranks repeats. |
| FastAPI surface (`api/main.py`) | **Implemented but unwired.** `GET /health` is live; `POST /analyze` validates input and mints a run ID, then returns an empty report. |
| Stage contracts (`models/`) | **Implemented.** `ExtractedQuery`, `Provenance`, `QueryKind`, `Finding`, `Severity`, `Evidence`, `Suggestion`, `Report`, `RunContext`. |
| Sandbox fixture app (`queryguard-sandbox/`) | **Implemented.** Builds and runs; seeds 5,000 customers; four planted bugs each beside a healthy counterpart. |

### The static rules

Rules take a parsed `sqlglot` AST, never a raw string. Each returns `Finding`s carrying a
severity, an `explanation` (what was found), an `impact` (why it matters at scale), and a
suggested fix. One rule per file, named after the smell it detects.

| Rule | Severity | Detects |
| --- | --- | --- |
| `SelectStarRule` | MEDIUM | `SELECT *` anywhere, including qualified `t.*`. Excludes `COUNT(*)`. |
| `MissingWhereRule` | CRITICAL | `UPDATE`/`DELETE` with no `WHERE`. Excludes writes scoped by `USING` or `LIMIT`, and `TRUNCATE`. |
| `NoLimitRule` | HIGH | `SELECT` reading a whole table with no `LIMIT`/`FETCH`. Excludes subqueries, single-row aggregates, filtered queries, and `FROM`-less selects. |
| `UnindexedFilterRule` | HIGH | `WHERE` predicates on columns with no index. Needs schema context; silent without it. |
| `NonSargableRule` | MEDIUM | Leading-wildcard `LIKE`, a function wrapping a filtered column, explicit casts, and schema-detected implicit casts. |

Two design points worth knowing before you extend them:

- **Schema-dependent rules are silent by default.** The stub provider
  (`UNKNOWN_SCHEMA`) answers "I don't know" to every lookup, and `UnindexedFilterRule`
  then reports nothing. "No index on that column" is unfalsifiable from query text
  alone, so a rule that guessed would fire on every predicate in the diff. Real schema
  loading is `db/snapshot.py`'s job and is not built yet.
- **`NoLimitRule` only fires on an unfiltered scan.** Flagging every `SELECT` without a
  `LIMIT` would fire on most correct queries, including the sandbox's deliberately
  healthy `exportRecentOrders`. Judging a *filtered* but unlimited query needs
  cardinality, which is the plan stage's job — a static rule cannot tell
  `WHERE id = ?` from `WHERE status = 'active'`.

### Evidence, not just green tests

The static stage catches the sandbox's planted bugs through the real
extractor → engine path, and stays silent on their healthy counterparts:

```
CRITICAL  missing-where      UPDATE has no WHERE clause and affects every row
HIGH      no-limit           SELECT reads an entire table with no row limit
MEDIUM    select-s
tar        Query selects every column with `SELECT *`
```

`tests/unit/static_rules/test_planted_bugs_end_to_end.py` asserts each fixture string is
still present verbatim in the sandbox source it came from, so editing a planted bug fails
the test rather than silently testing SQL that no longer exists.

The p6spy stage has been run against a statement log captured from a real sandbox
execution (5,046 statements) and isolates the planted N+1:

```
count= 5000 variants= 5000 total= 12702ms  SELECT o1_0.id, o1_0.customer_id, … FROM orders …
count=    6 variants=    1 total=    14ms  SET ROLE 'queryguard'
```

5,000 executions with 5,000 distinct bind values, where two queries would have done. Equal
`count` and `variants` is what separates an N+1 from a caching problem, where one shape
would repeat with identical binds.

## What is not built yet

- **Six stages**: ingest, provision, plan analysis (`EXPLAIN`), HypoPG index simulation,
  N+1 detection, and report rendering — all still `NotImplementedError`.
- **The rest of extraction**: Java sources, Spring Data derived methods, and the
  diff dispatcher (`extract_queries`) that decides which extractor a changed file goes to.
  Only `.sql`-style input works today.
- **Five of the ~10 planned rules.** Still to write: `OFFSET`-based deep paging, `IN` lists
  that should be joins, cartesian products, and derived-method fan-out.
- **No GitHub or Claude integration.** Nothing is fetched, and no comment is ever posted,
  so the "one idempotent comment per PR" behaviour is unproven.
- **No database code path.** `db/session.py` and `db/provision.py` are stubs, which means the
  `BEGIN`/`ROLLBACK` and never-touch-a-real-database invariants in
  [CLAUDE.md](CLAUDE.md#non-negotiable-constraints) are currently documented intent, not
  enforced behaviour. They need tests the moment those modules gain bodies.
- **`/analyze` does not run the pipeline.** The static stage works but nothing calls it
  from the API; wiring it is the next obvious step.
- **Missing entirely**: `config.py`, `cli.py`, `docker/`, `java-parser/`, API routes and DI,
  integration tests, CI workflows, and the `java/`, `plans/`, `diffs/` fixture corpora.
- **Lint and typecheck have not been run** against the new code. CLAUDE.md requires
  `ruff check`, `ruff format`, and strict `mypy`; treat the static-rules code as
  unverified against all three.

## Quick start

```bash
pip install -r requirements.txt
pytest                                       # 150 tests, no Docker or JDK needed
uvicorn queryguard.api.main:app --reload     # GET /health, POST /analyze
```

Run one rule's suite, or everything static:

```bash
pytest tests/unit/static_rules/ -v
pytest tests/unit/static_rules/test_no_limit.py -v
```

### Test layout

```
tests/unit/static_rules/    92 tests   five rule suites + engine + end-to-end
tests/unit/                 58 tests   sandbox fixture guards, p6spy, placeholders, API
```

Every rule suite pairs each positive case with a false-positive guard — usually the
sandbox's healthy counterpart to the bug being caught. `tests/unit/static_rules/` holds a
cross-stage test rather than living under `integration/`, because in this repo
`integration` means "requires Docker" (see the marker in `pytest.ini`) and the static
stage deliberately runs before anything is provisioned.

## Where to look next

Wiring the implemented stages into `POST /analyze` is the shortest path to something
end-to-end: extract → static rules → a rendered report needs no Docker and no
credentials. After that, `db/snapshot.py` is what turns `UnindexedFilterRule` from silent
into useful.

See [CLAUDE.md](CLAUDE.md) for the pipeline stages, folder layout, and conventions, and
[queryguard-sandbox/README.md](queryguard-sandbox/README.md) for the fixture app — how to
run it, and how to capture a statement log of your own.
