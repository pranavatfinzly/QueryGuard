# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

**QueryGuard** is an AI-powered PR bot that reviews database queries for performance
problems before they merge. On every pull request it analyzes:

- Raw SQL (files, migrations, string literals)
- JPQL / HQL (`@Query` annotations, `EntityManager.createQuery`)
- JPA native queries (`@Query(nativeQuery = true)`, `createNativeQuery`)
- Spring Data derived query methods (`findByCustomerIdAndStatusOrderByCreatedAtDesc`)

It posts a single idempotent, tagged Markdown comment on the PR explaining what it
found, why it is slow, and a suggested fix — backed by a real `EXPLAIN ANALYZE` plan,
measured index impact via HypoPG, and cross-query N+1 detection powered by Claude.

> **Naming note:** the README currently titles the project `hades`. Treat **QueryGuard**
> as the project name in code, docs, and comments unless told otherwise, and flag the
> README mismatch rather than silently renaming either one.

## Non-negotiable constraints

These are the invariants of the product. Do not weaken them for convenience.

1. **Never connect to a developer or production database.** Every run clones an
   isolated reference database from a schema snapshot/dump. If a code path could read
   a real connection string from CI, that is a bug.
2. **Every query execution is wrapped in `BEGIN` … `ROLLBACK`.** No statement may
   commit against the reference DB. This applies to `EXPLAIN ANALYZE`, HypoPG index
   creation, and any ad-hoc probing.
3. **Analysis is read-only with respect to the PR.** QueryGuard comments; it never
   pushes commits, edits files, or approves/blocks merges on its own.
4. **One comment per PR, updated in place.** Comments carry a hidden marker
   (e.g. `<!-- queryguard:report -->`) so re-runs edit the existing comment instead of
   spamming the thread.
5. **Fail soft.** A crashed stage degrades the report (a "could not analyze" note); it
   must not fail the PR check or block the pipeline unless explicitly configured to.

## Tech stack

| Concern | Choice |
| --- | --- |
| API / orchestration | FastAPI (Python 3.11+) |
| SQL parsing & dialect handling | `sqlglot` |
| Java source parsing (JPA/JPQL/derived methods) | JavaParser (invoked as a sidecar/JAR) |
| Runtime SQL capture from Java | p6spy |
| Reference database | Docker + Postgres 16 + HypoPG extension |
| LLM analysis (N+1, explanations) | Claude API (`claude-opus-5`) via the `anthropic` SDK |
| GitHub integration | PyGithub |
| CI | GitHub Actions |

## Pipeline stages

The run is a linear pipeline; each stage takes the previous stage's typed output.
Keep stages independently testable — no stage should reach into GitHub or Docker
directly except the ones that own those concerns.

1. **Ingest** — Receive the PR event (webhook or Actions run). Fetch the diff via
   PyGithub, resolve changed files and hunks, and record base/head SHAs.
2. **Extract** — Pull candidate queries out of the diff. `sqlglot` handles `.sql`
   files and SQL string literals; JavaParser walks Java sources for `@Query`
   annotations, `createQuery`/`createNativeQuery` calls, and Spring Data repository
   method names. Each extracted query keeps its provenance (`file:line`, kind,
   dialect) so findings can be anchored back to the diff.
3. **Static analysis** — Run rule checks on the parsed ASTs before touching a
   database: `SELECT *`, missing `WHERE`, leading-wildcard `LIKE`, functions wrapping
   indexed columns, implicit casts, unbounded result sets, `OFFSET`-based deep paging,
   `IN` lists that should be joins, cartesian products, and derived-method patterns
   that fan out. Rules are cheap, deterministic, and run even if provisioning fails.
4. **Provision** — Start an isolated Postgres 16 container from the reference schema
   snapshot and `CREATE EXTENSION hypopg`. One database per PR run, torn down
   afterwards. Never reuse a container across runs.
5. **Plan analysis** — For each executable query, bind placeholder parameters and run
   `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` inside `BEGIN` / `ROLLBACK`. Parse the
   plan tree for sequential scans on large tables, bad row estimates, nested-loop
   blowups, external sorts, and spilled hashes.
6. **Index simulation** — Propose candidate indexes from the plan and predicates, then
   create them hypothetically with `hypopg_create_index`, re-run `EXPLAIN` (no
   `ANALYZE` — hypothetical indexes are plan-only), and record the before/after cost
   comparison. Only surface an index whose simulated cost improvement clears a
   configured threshold. Reset with `hypopg_reset` between candidates.
7. **N+1 detection** — Give Claude the whole diff's query set plus repository/entity
   context (and, where available, p6spy-captured statement logs from the test suite)
   and ask it to identify N+1 access patterns that no single-query rule can see: a
   query inside a loop, a lazy association dereferenced per row, a derived method
   called per element of a collection. This stage reasons across queries, not within
   one.
8. **Report** — Merge static findings, plan findings, index suggestions, and N+1
   findings into a ranked Markdown report with severity, evidence (plan excerpts,
   cost deltas), and a suggested fix per finding. Then upsert the tagged comment on
   the PR.

## Recommended folder structure

Planned layout — create directories as the corresponding stage is implemented rather
than scaffolding empty packages up front.

```
queryguard/
├── api/                     # FastAPI app
│   ├── main.py              # app factory, lifespan, health/readiness
│   ├── routes/
│   │   ├── webhooks.py      # GitHub webhook receiver (signature verification)
│   │   └── runs.py          # manual/replay run triggers, run status
│   └── deps.py              # DI: settings, clients, db handles
├── pipeline/                # one module per stage, in run order
│   ├── ingest.py
│   ├── extract/
│   │   ├── sql.py           # sqlglot-based extraction + normalization
│   │   ├── java.py          # JavaParser sidecar client
│   │   └── derived.py       # Spring Data method-name -> query semantics
│   ├── static_rules/
│   │   ├── base.py          # Rule protocol, registry, severity enum
│   │   └── rules/           # one file per rule, named after the smell
│   ├── explain.py           # EXPLAIN ANALYZE inside BEGIN/ROLLBACK
│   ├── hypopg.py            # candidate indexes + before/after cost compare
│   ├── nplusone.py          # Claude-powered cross-query analysis
│   └── report.py            # findings -> ranked Markdown
├── db/
│   ├── provision.py         # Docker/Postgres lifecycle for the reference DB
│   ├── snapshot.py          # schema dump loading, migration replay
│   └── session.py           # connection/transaction helpers (rollback-only)
├── integrations/
│   ├── github.py            # PyGithub wrapper, idempotent tagged comment upsert
│   ├── claude.py            # Anthropic client, prompts, structured outputs
│   └── p6spy.py             # parse captured statement logs
├── models/                  # Pydantic models — the contracts between stages
│   ├── query.py             # ExtractedQuery, QueryKind, Provenance
│   ├── finding.py           # Finding, Severity, Evidence, Suggestion
│   └── report.py            # Report, RunContext
├── config.py                # pydantic-settings; all env/secrets land here
└── cli.py                   # local runs against a diff or a directory

java-parser/                 # JavaParser sidecar (Gradle/Maven project)
├── src/main/java/...        # emits JSON on stdout; no analysis logic here
└── build.gradle

docker/
├── postgres-hypopg.Dockerfile
└── docker-compose.dev.yml

tests/
├── unit/                    # pure logic: rules, parsers, report rendering
├── integration/             # real Postgres+HypoPG via testcontainers
├── fixtures/
│   ├── sql/                 # query corpus, one file per smell
│   ├── java/                # repository/entity samples for the Java extractor
│   ├── plans/               # captured EXPLAIN JSON for offline plan tests
│   └── diffs/               # recorded PR payloads and diffs
└── conftest.py

.github/workflows/
├── ci.yml                   # lint, typecheck, test
└── queryguard.yml           # the reusable workflow consumers call
```

## Coding conventions

### Python

- **Type hints everywhere.** Every function signature — parameters and return —
  is annotated. Run `mypy` (or `pyright`) in strict mode; a new `Any` needs a comment
  justifying it.
- **Pydantic models are the stage contracts.** Stages exchange models from
  `queryguard/models/`, never bare dicts or tuples. If a stage needs a new field, add
  it to the model rather than smuggling it through a side channel.
- **`pytest` for all tests.** `pytest.mark.parametrize` over the fixture corpus for
  rules; `testcontainers` for anything that needs real Postgres + HypoPG. Unit tests
  must not require Docker — keep plan-parsing tests fed by captured JSON in
  `tests/fixtures/plans/`.
- Async where I/O warrants it (FastAPI routes, GitHub and Claude calls); plain sync
  functions for parsing and rule evaluation. Don't make a function `async` unless it
  awaits something.
- No bare `except`. Catch the specific exception; when a stage must fail soft, catch
  at the stage boundary, log with the run ID, and return a degraded result.
- Config comes from `config.py` only. No `os.environ` reads scattered through modules,
  and no secrets in log output — redact connection strings and tokens.
- Formatting and linting: `ruff format` + `ruff check`. Line length 100.
- Naming: rule classes are named after the smell they detect (`SelectStarRule`,
  `LeadingWildcardLikeRule`) and live one-per-file under `pipeline/static_rules/rules/`.

### SQL and database code

- Parse with `sqlglot`; never regex SQL. If `sqlglot` cannot parse a candidate, record
  it as unanalyzable rather than guessing.
- Every statement executed against the reference DB goes through the helpers in
  `db/session.py`, which own the `BEGIN`/`ROLLBACK` wrapper. Do not open raw cursors
  in pipeline modules.
- `hypopg_reset()` after each candidate index so simulations don't compound.
- Hypothetical indexes are visible to `EXPLAIN` but not to `EXPLAIN ANALYZE` — use
  plain `EXPLAIN` for the after-cost measurement.

### Java sidecar

- The sidecar only parses and emits JSON. All analysis stays in Python so rules have
  one home.
- Its JSON output shape is a versioned contract; changing it means updating
  `models/query.py` and the fixtures together.

### Claude usage

- Default model: `claude-opus-5`. Use the `anthropic` Python SDK — never raw HTTP.
- Use structured outputs (`output_config.format`) for the N+1 stage so findings
  deserialize into `models/finding.py` without ad-hoc parsing.
- Prompt caching: keep the system prompt and rule descriptions stable and cached; put
  the per-PR diff and query set after the cache breakpoint.
- Handle `stop_reason == "refusal"` before reading `response.content`.
- Findings from Claude are claims, not facts. Where a claim is checkable against a
  plan or the AST, verify it before publishing; where it isn't, label the confidence
  in the report.

### Testing expectations

- Every new static rule ships with fixtures: at least one query it must flag and one
  similar query it must not (the false-positive guard).
- Plan-parsing changes ship with a captured `EXPLAIN` JSON fixture.
- Report rendering is snapshot-tested — the comment format is user-facing.
- The GitHub comment upsert has a test proving a second run edits rather than adds.

## Local development

Bring up the reference Postgres with HypoPG from `docker/docker-compose.dev.yml`, then
drive a single run through `queryguard/cli.py` against a recorded diff in
`tests/fixtures/diffs/` — that path needs no GitHub credentials and is the fastest way
to iterate on rules, plan analysis, or report formatting.
