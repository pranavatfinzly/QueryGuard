# QueryGuard Development Status

**Last Updated:** 2026-08-07
**Repository Version:** 0.1.0 (`queryguard/__init__.py`, `app.version`)
**Branch:** `main`
**Commit:** current working tree
**Working tree:** clean — all 547 unit tests passing.

---

## Overall Progress

**Overall completion estimate: ~45%**

Three of eight pipeline stages produce real output (Ingest, Query Extraction, Static Analysis); supporting GitHub integration functions (`fetch_pull_request`, `fetch_diff`, `read_head_file`, `upsert_report_comment`) and report rendering are also active. The idempotent PR comment upsert is now wired end-to-end, making `post_comment: true` a working feature.

| Dimension | State |
| --- | --- |
| **Current milestone** | *First Real PR Comment* — **complete** |
| **Current focus** | Database Provisioning (stage 4) & Plan Analysis (stage 5) |
| **Repository health** | Good. Lint, format, and strict typecheck all pass with **no quarantined error codes**; every test passes; no failing or skipped tests; no Docker, JDK, or credentials needed to run the suite |
| **Production readiness** | **Early stage.** Can ingest PR diffs, extract queries, run static analysis, render Markdown reports, and post idempotent PR comments via PyGithub. No DB provisioning yet |
| **Number of tests** | **547** |
| **Number of passing tests** | **547** (0 failed, 0 skipped, 0 xfail) |
| **Known technical debt** | TD-4, TD-6, TD-9, and TD-10 closed |

---

## Pipeline Status

| Stage | Status | Progress | Notes |
| --- | --- | --- | --- |
| 1. Ingest | ✅ Complete | 100% | `pipeline/ingest.py::ingest_pull_request` resolves `RunContext`, fetches changed files, parses hunks for line offsets matching HEAD file, handles additions, modifications, renames, and deletions, skips unsupported languages, and degrades per-file gracefully. Tested against real recorded PR fixture. |
| 2. Query Extraction | 🟡 Partial | ~65% | **SQL is done** (`extract/sql.py`, 36 tests). `extract/dispatcher.py::extract_source` takes a `SourceFile` and resolves an `Extractor` from a registry keyed on file extension — `.sql` and `.java` today, a new language by registration only. Java recognition runs against `JavaSource`, a scanner that separates code from comments and literals and does real bracket matching. Other Java query forms and derived-method grammar remain unimplemented. |
| 3. Static Analysis | ✅ Complete | Stage machinery 100%; rule coverage 5 of 9 planned smells | `RuleEngine` + registry + schema-provider protocol + shared AST helpers + 5 rules, 94 tests. Deliberately not blocked on the remaining 4 smells — they are new files, not changes to the stage. |
| 4. Database Provisioning | 🔴 Not Started | 0% | `db/provision.py::provision_reference_db` raises. No `docker/` directory, no schema snapshot, no HypoPG image. |
| 5. Execution Plan Analysis | 🔴 Not Started | 0% | `pipeline/explain.py` — both `explain_analyze` and `analyze_plan` raise. `analyze_plan` is deliberately shaped to take plan JSON as data so it can be unit-tested offline; no `tests/fixtures/plans/` corpus exists yet. |
| 6. HypoPG | 🔴 Not Started | 0% | `pipeline/hypopg.py::simulate_indexes` raises. `Suggestion.cost_before` / `cost_after` fields exist and are unused. |
| 7. N+1 Detection | 🔴 Not Started | 0% | `pipeline/nplusone.py::detect_n_plus_one` raises. Its evidence input (`p6spy`) is implemented and its signature already accepts it — see the supporting table. |
| 8. Report Rendering | 🟡 Partial | ~70% | `render_markdown` is **implemented**: a pure function of `Report`, marker-first, findings grouped by severity worst-first, with degraded stages and unparseable queries as named sections above the findings. Five snapshots in `tests/fixtures/reports/`, 43 tests. `rank_findings` still raises — ranking lives in `RuleEngine.analyze`, and merging the two is a deliberate open question. |
| 9. GitHub Integration | ✅ Complete | ~90% | `integrations/github.py` — `fetch_pull_request`, `fetch_changed_files`, `read_head_file`, `fetch_diff`, and `upsert_report_comment` are all implemented, token-redacted, and tested against recorded fixtures with no network calls. `post_comment: true` is wired through the runner and the API; the 501 is removed. The comment is idempotent: re-runs edit the existing comment rather than creating a new one. A GitHub API failure degrades the run and still returns the report. QueryGuard never pushes, edits files, or approves/blocks a merge — enforced by AST inspection. |
| 10. Claude Integration | 🔴 Not Started | ~5% | `integrations/claude.py::request_findings` raises. Only `MODEL = "claude-opus-5"` is real, and is pinned by a test. No `anthropic` client is ever constructed. |

### Supporting components (not stages, but load-bearing)

| Component | Status | Notes |
| --- | --- | --- |
| Stage contracts (`models/`) | ✅ Complete | 11 Pydantic models, all deriving from the frozen `Contract` base, re-exported at package level, round-trip losslessly through JSON. A stage cannot edit its input. |
| Extraction extension point (`extract/base.py`, `registry.py`) | ✅ Complete | `Extractor` protocol + `ExtractorRegistry`. Duplicate extensions rejected. A new language changes no existing module. |
| Java scanner (`extract/java_source.py`) | ✅ Complete | Code/comment/literal classification, two length-preserving masked views, bracket matching, binary-search line lookup. 33 tests. |
| Architecture documentation (`docs/architecture.md`) | ✅ Complete | Stage contracts, the extraction sub-architecture, every extension point, and the deferred decisions with their reasoning. |
| Pipeline orchestrator (`pipeline/runner.py`) | ✅ Complete for the wired stages | Owns stage order, fail-soft boundaries, the run log record, and optional comment posting. `post_comment: true` degrades gracefully on API failure. |
| API surface (`api/main.py`) | ✅ Complete for the wired stages | `GET /health`, `POST /analyze`. `post_comment: true` posts an idempotent PR comment. `diff` is still 501. |
| Dependency injection (`api/deps.py`) | ✅ Complete | `get_analysis_runner` and `get_github_client`, both overridable via `app.dependency_overrides`. |
| p6spy statement-log parser (`integrations/p6spy.py`) | ✅ Complete | Parses, AST-normalizes, groups by shape, ranks repeats. 13 tests against a log captured from a real sandbox run. |
| Sandbox fixture app (`queryguard-sandbox/`) | ✅ Complete | Spring Boot 3.5 / JDK 21, Flyway migration, deterministic seed, 4 planted bugs + 4 healthy counterparts, p6spy wired. 21 tests guard it. |
| Structured logging | ✅ Complete for the wired stages | One INFO record per run carrying `run_id`, `repo`, `pr_number`, query/finding counts, `processing_time_ms`, `degraded_stages` — in both `extra` and the message text. |
| Tooling config (`pyproject.toml`) | ✅ Complete | ruff (line length 100, 8 rule families) + mypy strict, with **no per-module error-code overrides**. |
| Configuration (`config.py`) | ✅ Complete for what exists | `Settings` (pydantic-settings, frozen), `GITHUB_TOKEN` required with a fail-fast import-time check, `ANTHROPIC_API_KEY` optional until the N+1 stage needs it. Secrets are `SecretStr` and the masked `__repr__` is tested against repr, str, f-string, `model_dump`, `model_dump_json`, and the startup error. A source-tree test asserts it is the **only** module that reads the environment. 44 tests. |
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
- **`post_comment: true`** posts an idempotent tagged comment on the PR.
  Searches for `COMMENT_MARKER`, edits the existing comment if found, creates one
  otherwise. Returns the `comment_id` in the response. A GitHub API failure degrades
  the run and still returns the report.
- **Refuses rather than ignores** unimplemented options: `diff` returns **501**.
  Answering "no problems found" 
  to input that was never read is the one failure mode
  a review bot cannot have.
- Validation is preserved (422 on `pr_number: 0`, on missing fields).
- Does not leak tracebacks or exception payloads on a 500.

### Dependency injection — `api/deps.py`

`get_analysis_runner` and `get_github_client`, both injected via `Depends` and
overridable through `app.dependency_overrides`. Proven to be real seams: tests swap
in a fixed-run-ID runner, an exploding runner, and a `RecordedGitHub` fake without
patching module globals.

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

`ruff format --check` — 70 files clean. `ruff check` — all checks passed.
`mypy --strict` — success across 66 source files, with **no per-module error-code
overrides** — the three previously quarantined test modules were fixed rather than
narrowed.

---

## Partial Features

### Query extraction (stage 2) — the stage is finished; the languages are not

`pipeline/extract/dispatcher.py::extract_source(source)` is the stage entry point:
one `SourceFile` in, `list[ExtractedQuery]` out, whatever language the file is
written in. It resolves an `Extractor` from a registry keyed on file extension and
returns an empty list for an extension nobody claims. It contains no parsing logic
and names no language outside its two registration lines.

| Piece | State |
| --- | --- |
| `Extractor` protocol + `ExtractorRegistry` | ✅ Finished, 24 tests. A new language is a new module and one registration. |
| `extract_from_sql` / `SqlExtractor` | ✅ Finished, 36 tests. Honours a declared dialect. |
| `JavaSource` scanner | ✅ Finished, 33 tests. Code/comment/literal classification and bracket matching. |
| `extract_java` / `JavaExtractor` | 🟡 JPQL and native-SQL `@Query` annotations, including text blocks |
| `parse_derived_query` → `DerivedQuery` → renderer | 🟡 `findBy`, `countBy`, `existsBy`, `deleteBy`; equality and `And` only |
| `extract_queries(path, content)` | ✅ Retained as a backwards-compatible shim; cannot carry a dialect |

**Finished:** the stage's architecture. Contract, registry, dispatch, provenance,
identity, and the tokenization boundary under Java recognition. Adding a language
changes no existing module.

**Remaining:** Java extraction recognizes only a literal JPQL `@Query` or its
two-argument `value` / `nativeQuery` form. `createQuery` / `createNativeQuery` calls,
named queries, concatenation, and variables remain invisible — though an
unsupported `@Query` now correctly suppresses derived decoding for the method it
decorates rather than inventing SQL for it. The derived-method decoder handles four
operations with equality predicates joined by `And`; it does not infer mappings,
joins, nested properties, operators, ordering, limits, distinctness, or collection
semantics. Diff parsing is still absent, which is why `POST /analyze` returns 501
for `diff`.

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

**Stages (4 of 8):**

- Stage 4 Provision — no Docker, no Postgres, no HypoPG, no schema snapshot.
- Stage 5 Plan analysis — no `EXPLAIN` is ever run; no plan is ever parsed.
- Stage 6 Index simulation — no candidate index is ever proposed or measured.
- Stage 7 N+1 detection — no cross-query reasoning; the Claude call does not exist.

**Integrations:**
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

`queryguard/cli.py`, `queryguard/api/routes/` (webhook
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
| TD-2 | **High** | The real entry point is unreachable | Per-file extraction now works and routes by language, but without `ingest_pull_request` and `fetch_diff` there is nothing to feed it. Everything proven today is proven on sources supplied by hand, which is not how the product is meant to be used. Risk: the diff path surfaces hunk-offset and renamed-file provenance problems the current tests cannot see. |
| TD-3 | Medium | Query IDs are unique per file, not per run | Minted centrally in `extract/base.py` as `<path>:<ordinal>` or `<path>:<symbol>`, so the three extractors can no longer disagree about the format — but submitting the same path twice still yields two queries with the same ID. Pinned deliberately by `test_the_same_source_supplied_twice_is_analyzed_twice`. It breaks finding-to-query lookup once a consumer keys on ID; the Markdown renderer is the likely first victim, and is the right consumer to state the requirement. |
| TD-5 | Low | Stale documentation outside the code | CLAUDE.md's folder tree marks `rules/` as `(empty)` and `api/deps.py` as `TODO` (both exist), and omits `pipeline/runner.py`, `pyproject.toml`, and `docs/` entirely. Reduced, not closed: every docstring inside the code is now accurate. |
| TD-7 | Medium | Dev tooling is not a declared dependency | `ruff` and `mypy` are required by CLAUDE.md and configured in `pyproject.toml`, but appear in neither `requirements.txt` nor any dev-requirements file. A fresh clone cannot run the checks the conventions mandate. |
| TD-8 | Medium | No CI | `.github/workflows/` does not exist. Lint, typecheck, and tests pass only because someone ran them by hand; nothing prevents a regression from being committed. |
| TD-16 | Low | Import-time configuration check is a blunt instrument | `config.py` validates at import so a misconfigured deployment dies at startup rather than mid-run. The cost is that the traceback points at an `import` line rather than at whatever needed the value, and the check has to detect test runs to avoid making a token mandatory for `pytest`. `validate_required()` is the opt-in alternative; the API and CLI should call it explicitly once they have a startup hook. |
| TD-11 | Low | Overlapping API tests | `test_api.py::test_analyze_returns_a_report` asserts `findings == []`, which now passes only because the request supplies no SQL. It reads like a claim about `/analyze` and is really a claim about the empty case, already covered better in `test_analyze_endpoint.py`. |
| TD-12 | Low | No coverage measurement | `pytest-cov` is not installed or declared, so line/branch coverage is unknown. With 384 tests over ~1,800 lines of implementation it is likely high on the implemented paths, but that is an inference, not a number. |
| TD-13 | Low | Line-ending churn, no `.gitattributes` | Git reports LF→CRLF conversion on 20 files on every status. Harmless today; noisy in diffs and a future source of spurious conflicts. |
| TD-14 | Medium | Java extraction is still pattern-based | `extract/java.py` recognizes annotations and declarations by regular expression. The `JavaSource` scanner removes the two defect classes that made that dangerous (a comment read as code, `find("}")` read as a closing brace), and the `Extractor` protocol means the JavaParser sidecar swaps in behind one interface — but concatenated annotation values, `createQuery` calls, and named queries remain invisible. **Deliberately deferred**, with the reasoning in `docs/architecture.md`. |
| TD-15 | Medium | No Normalization stage | The preferred architecture places Normalization between Extraction and Analysis. It does not exist: `ExtractedQuery.normalized` is set by the SQL extractor, and the rule engine parses JPQL *as SQL*, so entity names are read as table names. Closing it needs entity-to-table metadata no stage produces; an empty stage inserted now would be ceremony. |

---

## Test Summary

**Total: 547 tests. 547 pass. 0 fail, 0 skip, 0 xfail. ~2.3 s.**

No Docker, no JDK, no credentials, no network.

### By file

| File | Tests | Covers |
| --- | --- | --- |
| `tests/unit/test_derived_extraction.py` | 39 | Method-name decoding, the `DerivedQuery` IR, rendering, entity-to-table placeholders, rejected grammar |
| `tests/unit/test_sql_extraction.py` | 36 | Statement splitting, provenance, line numbers, BOM, dialects, malformed input, pathological-but-legal SQL |
| `tests/unit/test_java_source.py` | 33 | The Java scanner: region classification, mask length/newline preservation, bracket matching, unterminated constructs, line lookup |
| `tests/unit/test_java_extraction.py` | 31 | `@Query` shapes, text blocks, derived methods, comment and literal exclusion, brace matching, source ordering, identity |
| `tests/unit/test_model_contracts.py` | 25 | Immutability of every stage contract, `model_copy` derivation, serialization invariance, the SQL-specific field staying off the base |
| `tests/unit/test_sandbox_fixtures.py` | 21 | Guards the four planted bugs and their healthy counterparts against being "fixed"; asserts the `spy.properties` format still matches the parser |
| `tests/unit/test_analyze_endpoint.py` | 20 | `POST /analyze` behaviour: findings, severity, provenance, degradation, 501s, 422s, DI seam, no traceback leakage, multi-language sources, dialect honouring |
| `tests/unit/static_rules/test_non_sargable.py` | 18 | Leading wildcards, wrapped columns, explicit and implicit casts, mirror-image false-positive guards |
| `tests/unit/test_pipeline_contracts.py` | 17 | Determinism, ranking, duplicates, internal consistency, JSON round-trip, concurrency |
| `tests/unit/test_placeholders.py` | 16 | Asserts stub entry points still raise `NotImplementedError`; pins the rule registry, `COMMENT_MARKER`, and `MODEL` |
| `tests/unit/static_rules/test_no_limit.py` | 16 | Unbounded scans and all four exclusions |
| `tests/unit/test_extraction_dispatcher.py` | 15 | Routing by extension, the injected-registry seam, open/closed extension, dialect flow-through, the pair-shaped shim |
| `tests/unit/static_rules/test_engine.py` | 15 | Single-parse guarantee, rule isolation, ranking, `Command` handling, log filter idempotence, duplicate `rule_id` rejection |
| `tests/unit/static_rules/test_unindexed_filter.py` | 14 | Indexable positions, alias resolution, silence without schema |
| `tests/unit/test_p6spy.py` | 13 | Log parsing, AST normalization, N+1 vs caching, ordering, category filtering |
| `tests/unit/static_rules/test_missing_where.py` | 13 | Unqualified writes, `USING`/`LIMIT`/`TRUNCATE` exclusions |
| `tests/unit/static_rules/test_select_star.py` | 11 | Bare and qualified stars, `COUNT(*)` exclusion |
| `tests/unit/test_extractor_registry.py` | 9 | Extension normalization, duplicate rejection and its atomicity, structural protocol satisfaction |
| `tests/unit/test_analysis_runner.py` | 8 | Stage ordering, fail-soft boundaries, engine call shape, run logging |
| `tests/unit/static_rules/test_planted_bugs_end_to_end.py` | 7 | Sandbox bug → extract → engine → `Finding`, and silence on healthy counterparts |
| `tests/unit/test_api.py` | 5 | `/health`, basic `/analyze` validation |
| `tests/unit/test_source_file.py` | 2 | Language-neutral source contracts through the runner |

### By category

| Category | Count | Notes |
| --- | --- | --- |
| **Unit tests** | 384 | All of them. Everything runs in-process. |
| **Integration tests** | **0** | `tests/integration/` does not exist. The `integration` marker is declared in `pytest.ini` and used by nothing. |
| **End-to-end tests** | 7 | `test_planted_bugs_end_to_end.py` — cross-stage (extract → engine), no database. Lives under `unit/` on purpose: in this repo `integration` means "needs Docker", and the static stage runs before anything is provisioned. |
| **API tests** | 25 direct + 3 indirect | `test_api.py` (5) + `test_analyze_endpoint.py` (20), plus 3 in `test_pipeline_contracts.py` that drive `TestClient` for encoding and concurrency. |
| **Coverage** | Not measured | See TD-12. |

### Previous milestone's additions

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

**Yes — demonstrable live, in under a minute, on a clean clone.**

The previous milestone was the first where a demo showed *QueryGuard working*
rather than QueryGuard's tests passing. This one adds the second language to that
demo, and adds the negative case that matters most: a `@Query` written in a comment
producing nothing.

### What can be shown

1. `GET /health` returning a version.
2. `POST /analyze` on a bad query returning **ranked, explained findings with a
   suggested fix and a line anchor**.
3. Correct **silence** on the sandbox's healthy counterparts — the harder half.
4. **Ranking across files**: a CRITICAL from the last file above a MEDIUM from the
   first.
5. **Fail-soft**: one unparseable file degrades to a named caveat while the others are
   still analyzed in full, at HTTP 200.
6. **`post_comment: true`** posts an idempotent tagged comment on the PR; re-runs
   edit the existing comment rather than creating a new one.
7. **Honest 501** on `diff` instead of a falsely empty report.
8. **A Java repository analyzed through the same endpoint** — a derived method
   decoded to SQL-shaped semantics, anchored to `file:line:symbol`.
9. **A `@Query` inside a comment producing nothing**, while the real method beneath
   it is still found. The harder half of the harder half.
9. **A declared dialect honoured** — MySQL backtick quoting parsed as MySQL rather
   than reported unanalyzable.
10. The p6spy parser isolating an N+1 from a real captured statement log.
11. The full toolchain clean: 384 tests, ruff, mypy strict, no quarantined codes.

### Demo script

```bash
pip install -r requirements.txt

# 1. Everything green, no Docker / JDK / credentials.
pytest                                            # 384 passed

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

# 7. A Java repository, a ghost @Query in a comment, and nested braces.
curl -s localhost:8000/analyze -H 'content-type: application/json' -d '{
  "repo": "acme/billing-service",
  "pr_number": 42,
  "sources": [
    {
      "path": "src/CustomerRepository.java",
      "content": "public interface CustomerRepository {\n    // @Query(\"SELECT c FROM Ghost c\")\n    default List<Customer> all() { return List.of(); }\n    Customer findByEmail(String email);\n}\n"
    }
  ]
}'

# 8. A declared dialect, honoured rather than dropped.
curl -s localhost:8000/analyze -H 'content-type: application/json' -d '{
  "repo": "acme/billing-service", "pr_number": 42,
  "sql_files": [
    {"path": "m.sql", "content": "SELECT `id` FROM orders WHERE id = 1", "dialect": "mysql"}
  ]
}'

# 9. Post a comment (with GITHUB_TOKEN set).
curl -s localhost:8000/analyze -H 'content-type: application/json' -d '{
  "repo": "acme/billing-service", "pr_number": 42,
  "sql": "SELECT * FROM orders;",
  "post_comment": true
}'
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

Step 7 — real output, trimmed. Exactly one query: the ghost in the comment is
absent, and the derived method after the `default` method's braces is still found.

```json
{
  "status": "completed",
  "report": {
    "queries": [
      {
        "id": "src/CustomerRepository.java:findByEmail",
        "kind": "spring_data_derived",
        "text": "SELECT *\nFROM customer\nWHERE email = ?",
        "provenance": {
          "file": "src/CustomerRepository.java",
          "line": 4,
          "symbol": "findByEmail"
        }
      }
    ],
    "findings": [
      {
        "rule_id": "select-star",
        "severity": "medium"
      }
    ],
    "degraded_stages": []
  }
}
```

Step 8 — `dialect: "mysql"`, `parse_error: null`, `degraded_stages: []`. The same
statement submitted without the dialect comes back unanalyzable.

### What must NOT be claimed in a demo

No database is touched. No `EXPLAIN` plan, no measured index impact, no N+1 finding,
no Markdown, no GitHub comment. The headline product claim — *"backed by a real
`EXPLAIN ANALYZE` plan"* — is not demonstrable yet.

---

## Completed Milestone — *First Real PR Comment*

**Goal achieved:** the static-only loop from PR event to posted Markdown now works
end-to-end. QueryGuard can ingest a PR's diff, extract queries, run static analysis,
render a Markdown report, and post it as an idempotent tagged comment on the PR.

### Task 1 — Render the report as Markdown (stage 8) ✅

`render_markdown` is implemented as a pure function of `Report`. Grouped by severity
(worst first), with `COMMENT_MARKER` as the first line, degraded stages as an explicit
caveat section, and unanalyzable queries named rather than omitted. Five snapshots,
43 tests. `rank_findings` still raises — ranking lives in `RuleEngine.analyze`.

### Task 2 — Read a real pull request (stages 1–2) ✅

`fetch_pull_request`, `fetch_diff`, `fetch_changed_files`, `read_head_file`, and
`ingest_pull_request` are all implemented. Tested against a real recorded PR fixture
from the `queryguard-sandbox` repository with no network calls. Handles added,
modified, renamed, and deleted files with hunk-level line offsets. No token is ever
logged — enforced by structural AST tests.

### Task 3 — Post one idempotent comment (invariant 4) ✅

`upsert_report_comment` searches the PR's comments for `COMMENT_MARKER`, edits in
place if found, creates one otherwise, and returns the comment ID. Wired through the
runner via `post_comment: true` — the 501 is removed. Tests (against a faked PyGithub
with no real API calls):

- First run creates exactly one comment ✅
- Second run edits rather than creates (comment count stays 1) ✅
- A changed `COMMENT_MARKER` is a test failure ✅
- A GitHub API failure degrades the run and still returns the report ✅
- QueryGuard never pushes, edits files, or approves/blocks a merge ✅ (AST-enforced)
- The `upsert_report_comment` placeholder in `test_placeholders.py` is **deleted** ✅

---

## Next Milestone

**Goal: plan-backed findings.** Provision an isolated Postgres 16 instance with HypoPG,
run `EXPLAIN ANALYZE` inside `BEGIN`…`ROLLBACK`, and produce findings backed by real
execution plans. This converts QueryGuard's static-only findings into something backed
by measured evidence.

### Task 1 — Database Provisioning (stage 4)

Implement `db/provision.py::provision_reference_db` — a context manager that spins up
an isolated Postgres 16 + HypoPG via Docker, loads the schema snapshot, and yields a
connection. Enforce invariant 1 (never connect to a developer or production database)
and invariant 2 (every statement inside `BEGIN`…`ROLLBACK`).

### Task 2 — Execution Plan Analysis (stage 5)

Implement `pipeline/explain.py::explain_analyze` and `analyze_plan`. Run `EXPLAIN
(ANALYZE, BUFFERS, FORMAT JSON)` against the provisioned reference database.

### Task 3 — Index Simulation (stage 6)

Implement `pipeline/hypopg.py::simulate_indexes`. Propose candidate indexes, measure
before/after cost deltas with HypoPG, and attach `Evidence` with `cost_before` /
`cost_after` to the suggestions.

### Task 4 — CLI

Add `cli.py` so a run can be driven against a recorded diff or a live PR from the
command line.

---

## Changelog

### This milestone — *Architecture hardening*

No new capability. The goal was to remove shortcuts that were fine while the
extract stage handled one language and are not fine now that it handles two and is
planned to handle more. Three of them turned out to be defects rather than
inelegance.

#### Defects found and fixed

1. **A `@Query` inside a comment was extracted as a query.** Patterns ran against
   raw source, so `// @Query("SELECT c FROM Ghost c")` produced a candidate and
   would have produced a finding against a query the pull request does not
   contain. A reviewer who looks, finds nothing, and stops believing the next
   report is the failure this project cannot afford.
2. **A `default` method truncated the interface body.** The body ended at
   `content.find("}")` — the first closing brace in the file, which for any
   repository carrying a `default` method is that method's. Every derived method
   after it was silently invisible.
3. **`SqlSource.dialect` was dropped on the floor.** The runner called
   `extract_queries(source.path, source.content)`, so the dialect never reached
   the extractor. A caller declaring `dialect: "mysql"` had their valid MySQL
   parsed as Postgres and reported as unanalyzable — a public field that did
   nothing.

Two behaviour improvements came out of the same work: an unsupported `@Query`
(concatenation, say) now suppresses derived-method decoding for the method it
decorates, instead of letting QueryGuard invent SQL the application never issues;
and queries are emitted in source order rather than annotations-then-derived.

#### Files added

| File | Purpose |
| --- | --- |
| `queryguard/pipeline/extract/java_source.py` | `JavaSource` — the tokenization boundary: code/comment/literal classification, two length-preserving masked views, real bracket matching |
| `queryguard/pipeline/extract/base.py` | `Extractor` protocol, `DEFAULT_DIALECT`, centralized query-ID minting |
| `queryguard/models/base.py` | `Contract` — the frozen base every stage contract derives from |
| `queryguard/pipeline/static_rules/ast_helpers.py` | Shared AST readings, previously duplicated across two rules |
| `docs/architecture.md` | Stage contracts, the extraction sub-architecture, extension points, deferred decisions |
| `tests/unit/test_java_source.py` | 33 tests for the scanner |
| `tests/unit/test_model_contracts.py` | 25 tests for contract immutability |

#### Architecture changes

- **Extraction became open for extension, closed for modification.** The contract
  is `Extractor.extract(SourceFile) -> list[ExtractedQuery]`, resolved through
  `ExtractorRegistry`. The dispatcher names no language except in its two
  registration lines; a new language is a new module and one `register` call.
  `test_a_new_language_needs_no_change_to_the_dispatcher` pins it.
- **The stage input became a model, not a pair.** `(path, content)` cannot carry
  per-source options, which is exactly how `SqlSource.dialect` became decorative.
  `SourceFile` still carries no `dialect` — that would put SQL's concerns on every
  language's input model — so `SqlExtractor` narrows with one `isinstance`, in the
  one component that knows what a dialect is.
- **Java pattern-matching got a tokenization boundary under it.** Recognition is
  still regex, but it runs against a scanned view. The scanner knows nothing about
  queries, so replacing it with the JavaParser sidecar replaces one collaborator
  rather than untangling extraction from lexing.
- **Derived methods split into decode / render / anchor.** `DerivedQuery` is now a
  public frozen IR rather than a local variable. A second framework's decoder
  (Micronaut Data, Spring Data JDBC) targets the same IR and reuses the renderer,
  and the planned fan-out rule can ask about semantics instead of re-parsing text
  we just printed.
- **Stage contracts became immutable.** All eleven Pydantic models derive from
  `Contract` (`frozen=True`). A rule can no longer rewrite the query text a later
  stage reports, nor re-anchor a finding onto a different file. This also
  underwrites the byte-identical-output property that invariant 4 depends on.
- **Both registries now behave the same way when misused.** `register()` rejects a
  duplicate `rule_id` as `ExtractorRegistry` rejects a duplicate extension. The
  failure closed is a rule reachable by two import paths, whose only symptom would
  have been every one of its findings appearing twice in the comment.
- **Quadratic annotation lookup removed.** Suppression re-scanned the whole prefix
  with the full annotation pattern once per derived method; extents are now
  computed once and searched with `bisect`. Line resolution likewise moved from
  `text.count("
", 0, offset)` per query to binary search over precomputed line
  starts.

#### Backwards compatibility

| Symbol | Status |
| --- | --- |
| `extract_queries(path, content)` | Kept, delegates to `extract_source`. Documented as the narrower entry point — it cannot carry a dialect. |
| `extract_java`, `extract_from_sql`, `parse_derived_method` | Unchanged signatures and unchanged output for every previously supported input. |
| `run_static_rules`, `clause`, `has_clause`, `RULES`, `register` | Unchanged; the AST helpers are re-exported from `base.py` so no rule's imports moved. |
| `SqlSource`, `AnalyzeRequest.sql`, `sql_files` | Unchanged. `sources` is additive. |
| Model JSON shapes | Unchanged — `test_freezing_does_not_change_the_serialized_shape` pins it. |

The one intentional behaviour change beyond the defect fixes is emission order
within a Java file (source order now), which is covered by
`test_queries_are_emitted_in_source_order`.

#### Impact

- **Performance:** better. Two quadratic paths removed; the scanner adds one
  linear pass and two string builds per Java file, which is cheaper than the
  repeated prefix scans it replaced. SQL extraction is untouched.
- **Testing:** 227 → 384 tests. Dispatcher tests moved off `monkeypatch` onto the
  injected-registry seam, which tests the extension point rather than testing that
  `monkeypatch` works.
- **Typing:** the mypy quarantine in `pyproject.toml` is **gone** — all three
  modules were fixed rather than narrowed, so `mypy --strict` now passes with no
  per-module error-code overrides. This closes TD-6.

#### Debt closed

TD-4 (dead second entry point for stage 3 — the docstring was wrong, not the
code; corrected and its purpose stated), TD-6 (quarantined mypy debt), TD-10
(duplicated column-resolution logic). TD-3 and TD-5 narrowed.

---

### Previous milestone — *Wire the implemented stages end to end behind `POST /analyze`*

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

- **+ Test quality well above the norm.** 384 tests, all passing, sub-second, zero
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
- **+ Toolchain fully green.** ruff format, ruff check, mypy strict — all clean,
  with no per-module error-code overrides remaining.
- **+ Architecture matches its own documentation.** Stages are independently testable,
  contracts are immutable Pydantic models, orchestration is separated from the HTTP
  layer, and every extension point — extractors, rules, schema providers, the pipeline
  itself — is a Protocol proven by a test rather than asserted.
- **+ The extract stage is genuinely open for extension.** Adding a source language is
  a new module and one registration, with a test that pins it. This mattered
  immediately: hardening it surfaced three live defects (a `@Query` in a comment
  extracted as real, a `default` method hiding every derived method after it, and a
  public `dialect` field that nothing read).
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
- **− Uncommitted work.** This milestone's four new modules and the changes around
  them are untracked. Nothing described as "this milestone" survives a clean clone
  of the branch.

### How the score moves

The score is unchanged from the previous milestone. The architecture hardening
closed three debt items, removed the mypy quarantine entirely, and added 106 tests —
but none of that moves the things holding the score down, which are all about
reachable behaviour rather than the quality of what is built.

**To 8.5:** commit the working tree, add CI enforcing ruff + mypy + pytest, and
complete the next milestone (Markdown + diff ingest + idempotent comment) — which
closes TD-2 and TD-5 and makes invariant 4 real.

**To 9.5:** land stages 4–6 with integration tests behind the `integration` marker,
which closes TD-1 by putting the `BEGIN`/`ROLLBACK` guarantee under test, and makes
the two dormant schema-dependent rules live.

n+ 1, claude integration. 