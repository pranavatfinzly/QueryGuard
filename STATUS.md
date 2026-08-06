# QueryGuard Development Status

**Last Updated:** 2026-08-06
**Repository Version:** 0.1.0 (`queryguard/__init__.py`, `app.version`)
**Branch:** `restructure-pipeline-and-wire-p6spy`
**Commit:** `df1bd3c` — *restructured pipeline*
**Working tree:** dirty — 22 tracked files modified, 7 untracked. The pipeline
orchestrator (`queryguard/pipeline/runner.py`), the DI module
(`queryguard/api/deps.py`), `pyproject.toml`, and four test modules described below
are **not yet committed**. Everything in this document reflects the working tree, not
`df1bd3c`.

---

## Overall Progress

**Overall completion estimate: ~30%**

The count that matters is not lines of code but reachable behaviour. Two of eight
pipeline stages produce real output; the remaining six raise `NotImplementedError`.
What lifts the estimate above "2 of 8" is that the supporting scaffolding is
disproportionately finished: the stage contracts, the API surface, dependency
injection, the orchestrator, fail-soft boundaries, the p6spy evidence parser, the
sandbox fixture app, and the full lint/typecheck configuration all exist and are
tested.

| Dimension | State |
| --- | --- |
| **Current milestone** | *Wire the implemented stages end to end behind `POST /analyze`* — **complete** |
| **Current focus** | Report rendering (stage 8) and the diff dispatcher (stage 2), which together turn the working static path into a real PR comment |
| **Repository health** | Good. Lint, format, and strict typecheck all pass; every test passes; no failing or skipped tests; no Docker, JDK, or credentials needed to run the suite |
| **Production readiness** | **Not production ready.** No stage touches a database, no PR is ever read, no comment is ever posted. Usable today only as a library and a local HTTP service for SQL you hand it directly |
| **Number of tests** | **245** |
| **Number of passing tests** | **245** (0 failed, 0 skipped, 0 xfail; 0.66 s wall clock) |
| **Known technical debt** | 13 items tracked below — 2 High, 6 Medium, 5 Low. The two High items are both "the invariant is documented but nothing enforces it yet" |

### The one-sentence summary

QueryGuard can today take SQL, extract every statement from it with correct
provenance, run five deterministic rules over the parsed ASTs, and return a ranked,
JSON-serializable report over HTTP — fail-soft, deterministically, and
concurrency-safe. It cannot yet read a pull request, execute anything against a
database, or post a comment.

---

## Pipeline Status

| Stage | Status | Progress | Notes |
| --- | --- | --- | --- |
| 1. Ingest | 🔴 Not Started | 0% | `pipeline/ingest.py::ingest_pull_request` raises `NotImplementedError`. `RunContext` exists and carries `base_sha` / `head_sha` fields, but nothing populates them. |
| 2. Query Extraction | 🟡 Partial | ~50% | **SQL is done** (`extract/sql.py`, 36 tests). `extract/dispatcher.py::extract_queries` routes `.sql` to SQL extraction and `.java` to narrow JPQL `@Query` extraction, always returning `list[ExtractedQuery]`. Native Java queries and Spring Data derived methods remain unimplemented. |
| 3. Static Analysis | ✅ Complete | Stage machinery 100%; rule coverage 5 of 9 planned smells | `RuleEngine` + registry + schema-provider protocol + 5 rules, 92 tests. Deliberately not blocked on the remaining 4 smells — they are new files, not changes to the stage. |
| 4. Database Provisioning | 🔴 Not Started | 0% | `db/provision.py::provision_reference_db` raises. No `docker/` directory, no schema snapshot, no HypoPG image. |
| 5. Execution Plan Analysis | 🔴 Not Started | 0% | `pipeline/explain.py` — both `explain_analyze` and `analyze_plan` raise. `analyze_plan` is deliberately shaped to take plan JSON as data so it can be unit-tested offline; no `tests/fixtures/plans/` corpus exists yet. |
| 6. HypoPG | 🔴 Not Started | 0% | `pipeline/hypopg.py::simulate_indexes` raises. `Suggestion.cost_before` / `cost_after` fields exist and are unused. |
| 7. N+1 Detection | 🔴 Not Started | 0% | `pipeline/nplusone.py::detect_n_plus_one` raises. Its evidence input (`p6spy`) is implemented and its signature already accepts it — see the supporting table. |
| 8. Report Rendering | 🔴 Not Started | ~15% | `pipeline/report.py` — `rank_findings` and `render_markdown` both raise. Severity ranking *is* implemented, but inside `RuleEngine.analyze`, not here. No Markdown is produced anywhere. |
| 9. GitHub Integration | 🔴 Not Started | ~5% | `integrations/github.py` — all three functions raise. Only `COMMENT_MARKER` (`<!-- queryguard:report -->`) is real, and is pinned by a test. |
| 10. Claude Integration | 🔴 Not Started | ~5% | `integrations/claude.py::request_findings` raises. Only `MODEL = "claude-opus-5"` is real, and is pinned by a test. No `anthropic` client is ever constructed. |

### Supporting components (not stages, but load-bearing)

| Component | Status | Notes |
| --- | --- | --- |
| Stage contracts (`models/`) | ✅ Complete | 10 Pydantic models, re-exported at package level, round-trip losslessly through JSON. |
| Pipeline orchestrator (`pipeline/runner.py`) | ✅ Complete for the wired stages | Owns stage order, fail-soft boundaries, and the run log record. Extends per stage as stages land. **Uncommitted.** |
| API surface (`api/main.py`) | ✅ Complete for the wired stages | `GET /health`, `POST /analyze`. Unimplemented options are refused with 501 rather than silently ignored. |
| Dependency injection (`api/deps.py`) | ✅ Complete | `get_analysis_runner`, cached, overridable via `app.dependency_overrides`. **Uncommitted.** |
| p6spy statement-log parser (`integrations/p6spy.py`) | ✅ Complete | Parses, AST-normalizes, groups by shape, ranks repeats. 13 tests against a log captured from a real sandbox run. |
| Sandbox fixture app (`queryguard-sandbox/`) | ✅ Complete | Spring Boot 3.5 / JDK 21, Flyway migration, deterministic seed, 4 planted bugs + 4 healthy counterparts, p6spy wired. 21 tests guard it. |
| Structured logging | ✅ Complete for the wired stages | One INFO record per run carrying `run_id`, `repo`, `pr_number`, query/finding counts, `processing_time_ms`, `degraded_stages` — in both `extra` and the message text. |
| Tooling config (`pyproject.toml`) | ✅ Complete | ruff (line length 100, 8 rule families) + mypy strict. **Uncommitted.** |
| Configuration (`config.py`) | 🔴 Not Started | Does not exist. Nothing reads `os.environ` anywhere yet, so the convention is currently satisfied by having no configuration at all. |
| CLI (`cli.py`) | 🔴 Not Started | Does not exist. |
| Java sidecar (`java-parser/`) | 🔴 Not Started | Does not exist. |
| CI (`.github/workflows/`) | 🔴 Not Started | Does not exist. Lint/typecheck/test are enforced by hand only. |

---

## Implemented Features

Everything in this section was verified by reading the code and running it. Nothing
here is aspirational.

### SQL extraction — `pipeline/extract/sql.py`

- Splits multi-statement content using **`sqlglot.parse` and the tokenizer**, never
  `content.split(";")`. A semicolon inside a string literal or a `$$ … $$`
  dollar-quoted function body is correctly not treated as a boundary.
  *Evidence:* `test_a_semicolon_inside_a_string_literal_is_not_a_boundary`,
  `test_a_dollar_quoted_body_is_one_statement_however_many_semicolons_it_holds`.
- Preserves each statement **verbatim as written** (`text`), and records the sqlglot
  re-rendered form separately (`normalized`). A report never quotes SQL the author
  did not write.
  *Evidence:* `test_text_is_the_query_as_written_not_as_re_rendered`.
- Resolves a real starting **line number** per statement from token positions,
  surviving headers, blank lines, comments, CRLF line endings, and statements sharing
  a line.
  *Evidence:* 4 dedicated tests plus `test_line_numbers_match_what_the_extractor_recorded`.
- Correctly skips segments that hold no query — a stray `;;`, a trailing
  comment-only segment — **without shifting the text or line of every statement
  after it**. This was a real defect class; three tests pin it.
- Strips a UTF-8 BOM, which otherwise made an entire file unanalyzable.
- Records unparseable input as **one candidate with `parse_error` set** rather than
  dropping it, for both `ParseError` and `TokenError`.
- Honours and records the dialect.

### Static rule engine — `pipeline/static_rules/`

- `RuleEngine` parses each query **exactly once**, hands the AST to every registered
  rule, and sorts findings worst-severity-first with a stable sort (so equal
  severities keep source order).
- **Per-rule failure isolation:** a rule that raises loses its own check and nothing
  else, logged with the query ID.
- Skips queries the extract stage already marked unparseable (no double-reporting)
  and sqlglot `Command` fallback nodes (nothing structured to inspect).
- Installs an idempotent log filter that suppresses sqlglot's
  "contains unsupported syntax" warning, which on a real statement log is one line
  per statement.
- Import-time rule registration, with a test asserting the registry contains exactly
  the five expected rule IDs — so a rule file nobody imports fails the suite instead
  of silently never running.

### The five static rules

| Rule | ID | Severity | Detects |
| --- | --- | --- | --- |
| `MissingWhereRule` | `missing-where` | CRITICAL | `UPDATE`/`DELETE` with no `WHERE`. Excludes writes scoped by `USING` or `LIMIT`, and `TRUNCATE`. |
| `NoLimitRule` | `no-limit` | HIGH | `SELECT` reading a whole table with no `LIMIT`/`FETCH`. Excludes subqueries, single-row aggregates, filtered queries, and `FROM`-less selects. |
| `UnindexedFilterRule` | `unindexed-filter` | HIGH | Indexable `WHERE` predicates on columns with no leading index. Requires schema context. |
| `SelectStarRule` | `select-star` | MEDIUM | `SELECT *` at any depth, including qualified `t.*`. Excludes `COUNT(*)`. |
| `NonSargableRule` | `non-sargable` | MEDIUM | Leading-wildcard `LIKE`, a function wrapping a filtered column, explicit casts on a column, and schema-detected implicit casts. |

Every rule emits a `Finding` carrying a **required** `impact` field — the consequence
at scale, not a restatement of the match — plus at least one `Suggestion`. Every rule
suite pairs each positive case with a false-positive guard, usually the sandbox's
healthy counterpart.

Two deliberate design decisions, both documented in code and both worth preserving:

- **Schema-dependent rules are silent by default.** `UNKNOWN_SCHEMA` answers "I don't
  know" to every lookup, so `UnindexedFilterRule` and the implicit-cast half of
  `NonSargableRule` report nothing without a real schema. "No index on that column" is
  unfalsifiable from query text alone.
- **`NoLimitRule` only fires on an unfiltered scan.** Flagging every unlimited
  `SELECT` would fire on most correct queries. Judging a filtered-but-unlimited query
  needs cardinality, which belongs to stage 5.

### Schema context — `pipeline/static_rules/schema.py`

`SchemaProvider` protocol, `UnknownSchema` stub, and a working `StaticSchemaProvider`
with case-insensitive identifier folding (unquoted identifiers fold to lower case in
Postgres). `TableSchema` records leading indexed columns and column types. The test
suite drives it with the sandbox's real index layout.

### Pipeline orchestration — `pipeline/runner.py`

- Drives extract → static analysis in order, holding **no per-run state**, so one
  shared instance safely serves FastAPI's threadpool.
- **Fail-soft per source:** extraction degrades as `extract:<path>`, so losing one
  file out of ten is distinguishable from losing all ten. Both ways a source can
  degrade (unparseable candidate, extractor raising) produce the same marker.
- **Fail-soft per stage:** a rule engine that raises in its own dispatch loop
  degrades to `static_rules` and still returns the extracted queries.
- Drives the engine in **one call over the whole query set**, so a CRITICAL finding in
  the last file outranks a MEDIUM in the first.
- Emits one structured INFO log line per run.
- Generates a UUID `run_id`, or uses one supplied by the caller.

### FastAPI surface — `api/main.py`

- `GET /health` → `{"status": "ok", "version": "0.1.0"}`.
- `POST /analyze` accepts `sql` (a snippet, reported against `inline.sql`) and/or
  `sql_files` (named `SqlSource`s), and returns the ranked `Report` with
  `status: "completed"` or `"degraded"`.
- **Refuses rather than ignores** unimplemented options: `diff` and
  `post_comment: true` both return **501**. Answering "no problems found" to input
  that was never read is the one failure mode a review bot cannot have.
- Validation is preserved (422 on `pr_number: 0`, on missing fields).
- Does not leak tracebacks or exception payloads on a 500.

### Dependency injection — `api/deps.py`

`get_analysis_runner`, `lru_cache`d to one process-wide runner, injected via
`Depends`. Proven to be a real seam: tests swap in a fixed-run-ID runner and an
exploding runner through `app.dependency_overrides` without patching module globals.

### Pydantic stage contracts — `models/`

`QueryKind`, `SqlSource`, `Provenance`, `ExtractedQuery`, `Severity`, `Evidence`,
`Suggestion`, `Finding`, `RunContext`, `Report`. All re-exported from
`queryguard.models`. Verified to round-trip losslessly through JSON and to serialize
enums as values.

### p6spy statement-log parser — `integrations/p6spy.py`

- Parses the `epoch_millis|elapsed_ms|category|sql` format that the sandbox's
  `spy.properties` emits, bounded to three separators so SQL containing `|` survives.
- Drops malformed lines rather than raising (a log truncated mid-write should still
  yield what landed), and strips a leading BOM so the first statement is not silently
  lost.
- **Normalizes literals out via the sqlglot AST**, not textual substitution — a
  regex cannot tell a literal from the same characters inside a quoted identifier or
  comment. `Command` fallbacks are left intact rather than reduced to `SHOW %s`.
- Groups by normalized shape, counting `count` **and** `distinct_variants`. Equal and
  large is the signature of an N+1; one shape repeating with identical binds is a
  caching problem instead — a distinction the suite tests both directions of.
- Excludes row-level p6spy categories (`result`/`resultset`), which say nothing about
  statement count.

### Sandbox fixture app — `queryguard-sandbox/`

Spring Boot 3.5 on JDK 21, Maven wrapper checked in, Flyway migration, p6spy wired
into the datasource. Deterministic seed (`20260805`) producing exactly 5,000
customers / 17,736 orders / 53,896 order items, with **skewed** distributions —
uniform data hides the problems QueryGuard looks for. Four planted bugs, each beside
a healthy counterpart; the destructive one is guarded behind a flag defaulting to
`false`. 21 tests guard the fixture, including that the `spy.properties` format still
matches what the Python parser expects.

### Toolchain

`ruff format --check` — 56 files clean. `ruff check` — all checks passed.
`mypy --strict` — success across 53 source files (with three test modules'
pre-existing debt quarantined by exact error code; see debt item TD-6).

---

## Partial Features

### Query extraction (stage 2) — the SQL third of three

`pipeline/extract/dispatcher.py::extract_queries(path, content)` is now the single
per-file extraction entry point. It selects the SQL extractor for `.sql`, narrow JPQL
`@Query` extraction for `.java`, and returns an empty `list[ExtractedQuery]` for every
other extension. It contains no parsing logic; downstream stages continue to consume
only `ExtractedQuery` objects.

| Piece | State |
| --- | --- |
| `extract_from_sql` | ✅ Finished, 36 tests |
| `extract_java` | 🟡 Simple JPQL `@Query` annotations and text blocks |
| `parse_derived_method` | 🔴 Stub |
| `extract_queries` (per-file dispatcher) | ✅ Routes `.sql` and `.java` |

**Finished:** everything needed to turn a `.sql` file or a SQL snippet into
`ExtractedQuery` objects with accurate provenance.

**Remaining:** Java extraction recognizes only a single string literal or text block
as the sole `@Query` argument. Native queries, `createQuery` /
`createNativeQuery` calls, named queries, concatenation, variables, and repository
method names remain invisible.
`parse_derived_method` has a documented design constraint but no body — and it is the
harder half, because the SQL a derived method emits is often *not* what the name
suggests (`findByCustomerId` on a `@ManyToOne` compiles to a join filtered on the
parent's primary key, not `orders.customer_id = ?`). Diff parsing is still absent,
which is why `POST /analyze` returns 501 for `diff`.

**Consequence:** QueryGuard's stated input is a pull request. Its actual input today
is SQL you hand it directly.

### Static analysis (stage 3) — the rule backlog

**Finished:** the stage itself. Engine, registry, protocol, context helper, schema
provider, failure isolation, ranking, and five rules covering seven of the eleven
smells CLAUDE.md names.

**Remaining:** four smells have no rule — `OFFSET`-based deep paging, `IN` lists that
should be joins, cartesian products, and derived-method fan-out. The last of these is
blocked on `parse_derived_method`; the other three are self-contained new files.

Two implemented rules are also **dormant in practice**: `UnindexedFilterRule` and
`NonSargableRule`'s implicit-cast check both need a real `SchemaProvider`, and the
only production provider is the stub. They are fully implemented and fully tested
against `StaticSchemaProvider` — they simply have nothing to read until
`db/snapshot.py` exists.

### Report rendering (stage 8) — ranking without rendering

**Finished:** the `Report` model, and severity ranking (implemented in
`RuleEngine.analyze`, plus a stable secondary order by source position).

**Remaining:** `render_markdown` and `rank_findings` are both stubs. No Markdown is
produced anywhere in the repository, so the user-facing comment format does not exist
and cannot yet be snapshot-tested. `Evidence` is a defined model with zero producers.

### Fail-soft (CLAUDE.md invariant 5) — proven where it is reachable

**Finished:** rule-level, source-level, and stage-level fail-soft, each with a test,
including one that monkeypatches the extractor into raising to reach the runner's
catch-all that malformed SQL alone cannot exercise.

**Remaining:** six stages have no fail-soft behaviour to test because they have no
behaviour. The pattern is established; applying it to provisioning failures (the case
the invariant was written for) is untested.

---

## Not Yet Implemented

**Stages (6 of 8):**

- Stage 1 Ingest — no PR is ever read.
- Stage 4 Provision — no Docker, no Postgres, no HypoPG, no schema snapshot.
- Stage 5 Plan analysis — no `EXPLAIN` is ever run; no plan is ever parsed.
- Stage 6 Index simulation — no candidate index is ever proposed or measured.
- Stage 7 N+1 detection — no cross-query reasoning; the Claude call does not exist.
- Stage 8 Report rendering — no Markdown.

**Integrations:**

- GitHub: no diff fetch, no SHA resolution, no comment upsert. The "one idempotent
  tagged comment per PR" behaviour (invariant 4) is **entirely unproven** — only the
  marker constant exists.
- Claude: no `anthropic` client is constructed; no prompt, no structured output
  schema, no prompt-cache breakpoint, no `stop_reason == "refusal"` handling.

**Database:**

- `db/session.py::rollback_transaction` — the single place that is supposed to own
  `BEGIN`/`ROLLBACK` is a stub. Invariant 2 is documented intent, not enforced code.
- `db/provision.py` — stub. Invariant 1 (never connect to a developer or production
  database) has no code path that could violate it *and* no code path that enforces
  it.
- `db/snapshot.py` — does not exist. This is what would make the two dormant
  schema-dependent rules live.

**Modules that do not exist at all:**

`queryguard/config.py`, `queryguard/cli.py`, `queryguard/api/routes/` (webhook
signature verification, run status), `java-parser/`, `docker/`,
`.github/workflows/ci.yml`, `.github/workflows/queryguard.yml`.

**Fixture corpora that do not exist:**

`tests/fixtures/sql/` (query corpus, one file per smell), `tests/fixtures/java/`,
`tests/fixtures/plans/` (captured `EXPLAIN` JSON), `tests/fixtures/diffs/` (recorded
PR payloads). Only `tests/fixtures/p6spy/` exists, holding a 10-line excerpt.

**Test categories that do not exist:**

`tests/integration/` — the directory is absent, though the `integration` marker is
declared in `pytest.ini`. No test uses testcontainers, real Postgres, or HypoPG.

**Also missing:** four static rules (above), rate limiting, retries, and any auth on
the HTTP surface.

---

## Technical Debt

| ID | Severity | Item | Detail and cost |
| --- | --- | --- | --- |
| TD-1 | **High** | Invariants 1 & 2 are unenforced | `db/session.py` and `db/provision.py` are stubs, so "never connect to a real database" and "every statement inside `BEGIN`…`ROLLBACK`" are prose in CLAUDE.md with no code and no tests behind them. These are the product's safety guarantees. They need tests written *with* the first line of body, not after. |
| TD-2 | **High** | The real entry point is unreachable | Without `extract_queries`, `ingest_pull_request`, and `fetch_diff`, nothing can analyze a pull request. Everything proven today is proven on SQL supplied by hand, which is not how the product is meant to be used. Risk: the diff path surfaces provenance and dispatch problems the current tests cannot see. |
| TD-3 | Medium | Duplicate query IDs | IDs are `<path>:<ordinal>`, so submitting the same path twice yields two queries with the same ID (`a.sql:1`, `a.sql:1`). Pinned deliberately by `test_the_same_source_supplied_twice_is_analyzed_twice`, but it will break finding-to-query lookup once a consumer keys on ID — the Markdown renderer is the likely first victim. |
| TD-4 | Medium | Two entry points for stage 3 | `base.py::run_static_rules` is a thin wrapper over `RuleEngine` that nothing calls — the runner uses `RuleEngine` directly. Dead code with a comment claiming it is "the stage entry point the pipeline and the API wiring name", which is no longer true. Delete it or route the runner through it. |
| TD-5 | Medium | Stale documentation inside the code | `static_rules/rules/__init__.py` still says *"Empty until the first rule lands"* — there are five. CLAUDE.md's folder tree marks `rules/` as `(empty)` and `api/deps.py` as `TODO` (it exists), and omits `pipeline/runner.py` and `pyproject.toml` entirely. |
| TD-6 | Medium | Quarantined mypy debt | `pyproject.toml` disables `union-attr`, `comparison-overlap`, and `arg-type` for three test modules (`test_sandbox_fixtures`, `test_placeholders`, `static_rules/conftest`). Scoped by exact code rather than blanket-ignored, and none of it is in shipped code — but it is still three modules not held to strict mode. |
| TD-7 | Medium | Dev tooling is not a declared dependency | `ruff` and `mypy` are required by CLAUDE.md and configured in `pyproject.toml`, but appear in neither `requirements.txt` nor any dev-requirements file. A fresh clone cannot run the checks the conventions mandate. |
| TD-8 | Medium | No CI | `.github/workflows/` does not exist. Lint, typecheck, and tests pass only because someone ran them by hand; nothing prevents a regression from being committed. |
| TD-9 | Medium | No configuration layer | `config.py` does not exist. Today that is fine — nothing reads `os.environ` anywhere — but the moment GitHub or Claude lands, the "config comes from `config.py` only, no secrets in logs" convention has to be honoured by a module that does not yet exist. |
| TD-10 | Low | Duplicated column-resolution logic | `_table_aliases` and `_resolve_table` are implemented twice, in `rules/unindexed_filter.py` and `rules/non_sargable.py`, with slightly different code. Both are alias-resolution helpers that belong in `base.py`; two copies will drift. |
| TD-11 | Low | Overlapping API tests | `test_api.py::test_analyze_returns_a_report` asserts `findings == []`, which now passes only because the request supplies no SQL. It reads like a claim about `/analyze` and is really a claim about the empty case, already covered better in `test_analyze_endpoint.py`. |
| TD-12 | Low | No coverage measurement | `pytest-cov` is not installed or declared, so line/branch coverage is unknown. With 227 tests over ~1,400 lines of implementation it is likely high on the implemented paths, but that is an inference, not a number. |
| TD-13 | Low | Line-ending churn, no `.gitattributes` | Git reports LF→CRLF conversion on 20 files on every status. Harmless today; noisy in diffs and a future source of spurious conflicts. |

---

## Test Summary

**Total: 227 tests. 227 pass. 0 fail, 0 skip, 0 xfail. 0.59 s.**

No Docker, no JDK, no credentials, no network.

### By file

| File | Tests | Covers |
| --- | --- | --- |
| `tests/unit/test_sql_extraction.py` | 36 | Statement splitting, provenance, line numbers, BOM, dialects, malformed input, pathological-but-legal SQL |
| `tests/unit/test_sandbox_fixtures.py` | 21 | Guards the four planted bugs and their healthy counterparts against being "fixed"; asserts the `spy.properties` format still matches the parser |
| `tests/unit/test_placeholders.py` | 19 | Asserts 16 stub entry points still raise `NotImplementedError`; pins the rule registry, `COMMENT_MARKER`, and `MODEL` |
| `tests/unit/static_rules/test_non_sargable.py` | 18 | Leading wildcards, wrapped columns, explicit and implicit casts, mirror-image false-positive guards |
| `tests/unit/test_pipeline_contracts.py` | 17 | Determinism, ranking, duplicates, internal consistency, JSON round-trip, concurrency |
| `tests/unit/test_analyze_endpoint.py` | 16 | `POST /analyze` behaviour: findings, severity, provenance, degradation, 501s, 422s, DI seam, no traceback leakage |
| `tests/unit/static_rules/test_no_limit.py` | 16 | Unbounded scans and all four exclusions |
| `tests/unit/static_rules/test_unindexed_filter.py` | 14 | Indexable positions, alias resolution, silence without schema |
| `tests/unit/test_p6spy.py` | 13 | Log parsing, AST normalization, N+1 vs caching, ordering, category filtering |
| `tests/unit/static_rules/test_missing_where.py` | 13 | Unqualified writes, `USING`/`LIMIT`/`TRUNCATE` exclusions |
| `tests/unit/static_rules/test_engine.py` | 13 | Single-parse guarantee, rule isolation, ranking, `Command` handling, log filter idempotence |
| `tests/unit/static_rules/test_select_star.py` | 11 | Bare and qualified stars, `COUNT(*)` exclusion |
| `tests/unit/test_analysis_runner.py` | 8 | Stage ordering, fail-soft boundaries, engine call shape, run logging |
| `tests/unit/static_rules/test_planted_bugs_end_to_end.py` | 7 | Sandbox bug → extract → engine → `Finding`, and silence on healthy counterparts |
| `tests/unit/test_api.py` | 5 | `/health`, basic `/analyze` validation |

### By category

| Category | Count | Notes |
| --- | --- | --- |
| **Unit tests** | 227 | All of them. Everything runs in-process. |
| **Integration tests** | **0** | `tests/integration/` does not exist. The `integration` marker is declared in `pytest.ini` and used by nothing. |
| **End-to-end tests** | 7 | `test_planted_bugs_end_to_end.py` — cross-stage (extract → engine), no database. Lives under `unit/` on purpose: in this repo `integration` means "needs Docker", and the static stage runs before anything is provisioned. |
| **API tests** | 21 direct + 3 indirect | `test_api.py` (5) + `test_analyze_endpoint.py` (16), plus 3 in `test_pipeline_contracts.py` that drive `TestClient` for encoding and concurrency. |
| **Coverage** | Not measured | See TD-12. |

### New this milestone

**+77 tests** (150 → 227), in four new files:

- `test_sql_extraction.py` (36) — the extract stage had **no tests at all** before
  this milestone, which was the worst gap in the repository: every `file:line` anchor
  and every quoted snippet in the eventual PR comment comes from there. Written
  against three real defects, all the same shape — `spans` and `statements` come from
  two different sqlglot passes, and pairing them by position desynchronizes as soon as
  a segment appears in one but not the other.
- `test_pipeline_contracts.py` (17) — the invariants that only appear once stages are
  assembled: byte-identical output for identical input (the PR comment is rewritten in
  place, so churn destroys trust), lossless JSON round-trip, every finding anchorable
  to a query in the same report, and 40 concurrent runs through one shared runner
  producing one distinct payload.
- `test_analyze_endpoint.py` (16) — behavioural tests for the newly wired endpoint.
- `test_analysis_runner.py` (8) — the orchestrator's fail-soft contracts.

Plus 4 tests added to `test_placeholders.py` as its scope narrowed (two stubs became
real), and revisions across the existing static-rule suites.

---

## Demo Status

**Yes — this milestone is demonstrable, live, in under a minute, on a clean clone.**

This is the first milestone where a demo shows *QueryGuard working* rather than
QueryGuard's tests passing.

### What can be shown

1. `GET /health` returning a version.
2. `POST /analyze` on a bad query returning **ranked, explained findings with a
   suggested fix and a line anchor**.
3. Correct **silence** on the sandbox's healthy counterparts — the harder half.
4. **Ranking across files**: a CRITICAL from the last file above a MEDIUM from the
   first.
5. **Fail-soft**: one unparseable file degrades to a named caveat while the others are
   still analyzed in full, at HTTP 200.
6. **Honest 501s** on `diff` and `post_comment` instead of a falsely empty report.
7. The p6spy parser isolating an N+1 from a real captured statement log.
8. The full toolchain clean: 227 tests, ruff, mypy strict.

### Demo script

```bash
pip install -r requirements.txt

# 1. Everything green, no Docker / JDK / credentials.
pytest                                            # 227 passed

# 2. Start the service.
uvicorn queryguard.api.main:app --reload

# 3. Health.
curl -s localhost:8000/health

# 4. A bad query — two findings, worst first.
curl -s localhost:8000/analyze -H 'content-type: application/json' -d '{
  "repo": "acme/billing-service", "pr_number": 42,
  "sql": "SELECT * FROM orders;"
}'

# 5. Ranking across files + fail-soft in one request.
curl -s localhost:8000/analyze -H 'content-type: application/json' -d '{
  "repo": "acme/billing-service", "pr_number": 42,
  "sql_files": [
    {"path": "migrations/001_orders.sql",    "content": "SELECT * FROM orders WHERE id = 1"},
    {"path": "migrations/002_broken.sql",    "content": "SELECT FROM WHERE"},
    {"path": "migrations/003_customers.sql", "content": "UPDATE customers SET loyalty_tier = 1"}
  ]
}'

# 6. Correct silence on healthy SQL.
curl -s localhost:8000/analyze -H 'content-type: application/json' -d '{
  "repo": "acme/billing-service", "pr_number": 42,
  "sql": "SELECT id, order_number, status FROM orders WHERE placed_at >= :since"
}'

# 7. Honest refusal.
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/analyze \
  -H 'content-type: application/json' \
  -d '{"repo":"acme/x","pr_number":1,"post_comment":true}'      # 501
```

### Expected output

Step 4 — real output, trimmed:

```json
{
  "run_id": "2c8ba92a-d05e-4c37-a187-915247d6270c",
  "status": "completed",
  "report": {
    "context": { "repo": "acme/billing-service", "pr_number": 42 },
    "queries": [
      { "id": "inline.sql:1", "kind": "raw_sql", "text": "SELECT * FROM orders",
        "provenance": { "file": "inline.sql", "line": 1 }, "parse_error": null }
    ],
    "findings": [
      { "rule_id": "no-limit", "severity": "high",
        "title": "SELECT reads an entire table with no row limit",
        "explanation": "This SELECT reads `orders` with no WHERE clause and no LIMIT/FETCH…",
        "impact": "Cost is proportional to table size with no ceiling…",
        "suggestions": [ { "description": "Decide what bounds this query and say it in SQL…" } ] },
      { "rule_id": "select-star", "severity": "medium",
        "title": "Query selects every column with `SELECT *`", "…": "…" }
    ],
    "degraded_stages": []
  }
}
```

Step 5 — `status: "degraded"`, HTTP **200**, `degraded_stages:
["extract:migrations/002_broken.sql"]`, findings present for `001` and `003` only.
Step 6 — `findings: []`, `degraded_stages: []`, `queries` length 1. Silence that means
*analyzed and clean*, not *never looked*.

### What must NOT be claimed in a demo

No database is touched. No `EXPLAIN` plan, no measured index impact, no N+1 finding,
no Markdown, no GitHub comment. The headline product claim — *"backed by a real
`EXPLAIN ANALYZE` plan"* — is not demonstrable yet.

---

## Next Milestone

**Goal: the first real pull-request comment.** Complete the static-only loop from PR
event to posted Markdown, with no Docker and no Claude. That converts QueryGuard from
a library with an HTTP surface into a working (if shallow) PR bot, and it exercises
invariant 4 — the one currently backed by nothing but a marker constant.

Deliberately sequenced before stages 4–6: provisioning is the largest and riskiest
piece of remaining work, and it is much easier to build against a pipeline that
already renders and posts.

### Task 1 — Render the report as Markdown (stage 8)

Implement `pipeline/report.py::render_markdown` and either implement `rank_findings`
or delete it and move ranking out of `RuleEngine` into it. Nothing new is needed as
input; `Report` already carries everything.

- Group by severity, worst first; one section per finding with `file:line`,
  the query, the explanation, the impact, and the suggestion.
- Emit `COMMENT_MARKER` as the first line.
- Surface `degraded_stages` as an explicit "could not analyze" caveat — a silent
  report over a partially-read diff is the failure mode invariant 5 exists to prevent.
- Render unanalyzable queries (`parse_error` set) as named caveats, not omissions.

*Acceptance:* snapshot tests for the empty report, findings-only, degraded-only, and
both; `render_markdown` is a pure function of `Report` (same report → byte-identical
Markdown); the marker is present and first; no fixture in the snapshot is the string
`None`.

### Task 2 — Read a real pull request (stages 1–2)

Implement `integrations/github.py::fetch_pull_request` and `fetch_diff`, then
`pipeline/ingest.py::ingest_pull_request`, then
`extract/__init__.py::extract_queries` — the dispatcher that routes a changed file to
`extract_from_sql` (today) or `extract_from_java` (later, unimplemented; it must
degrade, not raise). Add `config.py` here, because this is the first stage that needs
a token. Record a real PR payload and diff into `tests/fixtures/diffs/`.

*Acceptance:* `POST /analyze` with `diff` returns findings instead of 501; the
dispatcher handles added, modified, renamed, and deleted files, and hunk-level line
offsets, so a finding's line matches the **head** file; a Java file in the diff
degrades that file only; no token is ever logged; unit tests run from the recorded
fixture with no network.

### Task 3 — Post one idempotent comment (invariant 4)

Implement `upsert_report_comment`: search the PR's comments for `COMMENT_MARKER`,
edit if found, create otherwise, return the ID. Wire `post_comment: true` through the
runner and remove that 501. Add `cli.py` so a run can be driven against a recorded
diff with no GitHub credentials.

*Acceptance:* the test CLAUDE.md explicitly requires — a second run **edits** rather
than adds, proven against a faked PyGithub; a changed marker is a test failure, not a
silent duplicate comment; a GitHub failure degrades the run and still returns the
report; QueryGuard never pushes, edits files, or approves/blocks a merge.

### Milestone acceptance criteria

- A recorded PR fixture goes diff → extract → rules → Markdown → upsert, twice, with
  one comment existing at the end.
- The 501s on `diff` and `post_comment` are gone because both work.
- `config.py` is the only module reading the environment; no secret appears in any log
  or response.
- The corresponding cases in `test_placeholders.py` are **deleted**, not weakened —
  that file's shrinking is the progress metric.
- Comment format is snapshot-tested. 227 tests still pass. ruff and mypy strict still
  clean. TD-4 and TD-5 closed on the way past.

---

## Changelog

### This milestone — *Wire the implemented stages end to end behind `POST /analyze`*

Before this milestone, static analysis worked and nothing called it: `POST /analyze`
minted a run ID and returned an empty report with `status: "not_implemented"`. The
stage was real; the product was not. This milestone connected extract → static rules
→ HTTP response, and then wrote the tests that connection makes possible.

#### Files added

| File | Purpose |
| --- | --- |
| `queryguard/pipeline/runner.py` | `AnalysisRunner` — stage ordering, fail-soft boundaries, run logging |
| `queryguard/api/deps.py` | `get_analysis_runner` — the DI seam |
| `pyproject.toml` | ruff + mypy configuration (deliberately no `[project]` table; run from the source tree) |
| `tests/unit/test_sql_extraction.py` | 36 tests for a previously untested stage |
| `tests/unit/test_pipeline_contracts.py` | 17 cross-cutting invariants |
| `tests/unit/test_analyze_endpoint.py` | 16 endpoint behaviour tests |
| `tests/unit/test_analysis_runner.py` | 8 orchestrator tests |

#### Files modified

`api/main.py` (rewritten around the runner: `AnalyzeRequest.sql`/`sql_files`,
`AnalyzeResponse.from_report`, 501s for `diff`/`post_comment`), `models/query.py` (new
`SqlSource` contract), `models/__init__.py` (re-export it), `pipeline/extract/sql.py`
(BOM handling, span/statement desync fixes), `static_rules/engine.py` (`Command` and
non-`Expression` narrowing), `static_rules/rules/no_limit.py`,
`rules/non_sargable.py`, `rules/unindexed_filter.py` (typing precision for
`find_all`), `static_rules/schema.py`, `static_rules/__init__.py`,
`integrations/p6spy.py`, `integrations/github.py`, `pipeline/explain.py`,
`pipeline/extract/derived.py`, and eight test modules.

#### Architecture changes

- **A new layer: orchestration.** Stage ordering used to have no home. It now lives in
  `pipeline/runner.py`, not in the FastAPI route — otherwise the CLI and the eventual
  webhook handler would each grow their own copy of it. The API layer is left with
  request parsing and response shaping.
- **Dependency injection at the edge.** Routes declare what they need with `Depends`
  rather than importing it, so tests substitute the pipeline without patching module
  globals.
- **`SqlSource` promoted to a stage contract.** Path and content travel together often
  enough — several files, one failing must not lose the others — that they are a model
  rather than two loose arguments.
- **Degradation became addressable.** `degraded_stages` carries `extract:<path>`, not a
  bare `"extract"`: losing one file out of ten is a materially different report from
  losing all ten, and one marker cannot say which happened.

#### Behaviour changes

| Before | After |
| --- | --- |
| `POST /analyze` returned an empty report, `status: "not_implemented"` | Returns real ranked findings; `status` is `"completed"` or `"degraded"` |
| `diff` and `post_comment` were accepted and ignored | Refused with **501** and an explanatory detail |
| No way to submit SQL | `sql` (inline, reported against `inline.sql`) and `sql_files` (named sources) |
| No run logging | One structured INFO record per run, in `extra` and in the message |
| Unreadable SQL had no defined outcome at the API | HTTP 200, `status: "degraded"`, the source named, every other source still analyzed |

#### Bug fixes

Three defects in `extract_from_sql`, all the same shape — `spans` and `statements` are
computed by two different sqlglot passes, and pairing them by enumerate-position
desynchronizes as soon as a segment appears in one but not the other:

1. **A stray `;` shifted everything after it.** Every following statement was handed
   the *previous* statement's text and line number. Every anchor in a migration after
   a stray semicolon pointed at the wrong statement. Fixed by advancing the span
   cursor on queries actually built (`ordinal = len(queries)`), not on enumerate
   position.
2. **A comment-only segment did the same, and leaked.** `-- migration notes` on its
   own line parses to a `Semicolon` node carrying only a comment; it both shifted the
   statements after it and surfaced as a query of its own.
3. **A UTF-8 BOM made an entire file unanalyzable.** One stray byte turned a valid
   migration into "could not analyze". Editors on Windows write it by default, so this
   is ordinary input, not a corrupt file. Stripped before the empty check, so a
   BOM-only file is empty rather than unanalyzable. The same fix was applied to the
   p6spy parser, where a BOM silently dropped the *first* statement — the one most
   likely to matter.

#### Refactoring

- `has_clause` / `clause` helpers extracted into `static_rules/base.py`. `has_clause`
  tests truthiness rather than `is not None`, because sqlglot marks an absent clause
  inconsistently — `Delete.args["using"]` is `False` for a plain `DELETE`, so an
  `is not None` check reads as correct and silently treats every bare `DELETE` as
  scoped. `clause` accepts several keys because sqlglot renamed `from` to `from_`
  across versions.
- Typing precision for `find_all` with multiple node types, which resolves to the
  nearest common base (`Condition`, `Binary`) — beside `Expression` rather than under
  it, and declaring no `args`. Explicit `tuple[type[exp.Expression], ...]`
  annotations fixed this without `Any`.
- `_from_clause` reads args instead of `find(exp.From)`, which descends into
  subqueries — `SELECT (SELECT 1 FROM t)` looked like it had a `FROM` of its own and
  was flagged for scanning a table it never reads.
- **Toolchain brought to green for the first time.** `pyproject.toml` added; ruff
  format, ruff check, and mypy strict all pass, with pre-existing test-only debt
  quarantined by exact error code so the list can only shrink.

### Previous milestones

- **`df1bd3c` restructured pipeline** — the static rule engine and its five rules.
- **`9c8ce16`** — sandbox pinned to JDK 21 in docs; absolute timings removed in favour
  of in-run comparisons.
- **`0e3dfa3`** — restructured the flat `modules/` layout into the CLAUDE.md package
  tree; wired p6spy end to end.

---

## Repository Health Score

# 7.5 / 10

### What earns it

- **+ Test quality well above the norm.** 227 tests, all passing, sub-second, zero
  external dependencies. More importantly they test the *right* things: false-positive
  guards paired with every positive case, determinism, concurrency under a shared
  runner, lossless serialization, and internal consistency between findings and
  queries. Several were written against real defects rather than to cover lines.
- **+ Honesty is enforced mechanically.** `test_placeholders.py` asserts unimplemented
  stages *stay* unimplemented, so a stub cannot quietly appear finished.
  `test_planted_bugs_end_to_end.py` asserts each fixture SQL string still exists
  verbatim in the sandbox source, so editing a planted bug fails the suite instead of
  silently testing SQL that no longer exists. `/analyze` returns 501 rather than a
  falsely empty report. This is the single best thing about the repository.
- **+ Toolchain fully green.** ruff format, ruff check, mypy strict — all clean, with
  debt quarantined by exact error code rather than blanket-ignored.
- **+ Architecture matches its own documentation.** Stages are independently testable,
  contracts are Pydantic models, orchestration is separated from the HTTP layer, and
  the DI seam is proven by tests rather than asserted.
- **+ Judgement is documented, not just decisions.** The code explains why
  `NoLimitRule` excludes filtered queries, why schema-dependent rules stay silent, and
  why derived methods cannot be reasoned about from their names. That is what makes it
  extensible by someone else.
- **+ The sandbox produces real evidence.** Skewed distributions, a fixed seed, four
  bugs beside four healthy counterparts, and a guarded destructive fixture.

### What holds it back

- **− Two of eight stages work.** No amount of quality in the implemented 30% changes
  that the headline claim — findings backed by a real `EXPLAIN ANALYZE` plan and
  measured index impact — is not yet demonstrable.
- **− The safety invariants have no code behind them** (TD-1). `BEGIN`/`ROLLBACK` and
  never-touch-a-real-database are the product's promises and are currently prose.
- **− No CI** (TD-8). Everything green is green because someone ran it by hand.
- **− The real input path does not exist** (TD-2). Every proof is on SQL supplied
  directly, not on a diff.
- **− Zero integration tests.** The marker is declared and unused; nothing has ever
  run against Postgres or HypoPG.
- **− Uncommitted work.** The orchestrator, the DI module, the tooling config, and 77
  tests are untracked. Nothing described as "this milestone" survives a clean clone of
  the branch.

### How the score moves

**To 8.5:** commit the working tree, add CI enforcing ruff + mypy + pytest, and
complete the next milestone (Markdown + diff ingest + idempotent comment) — which
closes TD-2 and TD-5 and makes invariant 4 real.

**To 9.5:** land stages 4–6 with integration tests behind the `integration` marker,
which closes TD-1 by putting the `BEGIN`/`ROLLBACK` guarantee under test, and makes
the two dormant schema-dependent rules live.
