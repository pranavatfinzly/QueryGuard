# QueryGuard: what it is and why adopt it org-wide

The same content is maintained as a shared document; this copy lives with the code so it
is versioned and reviewable.

## Summary

QueryGuard is a bot that reads every pull request and flags database queries that will be
slow or dangerous in production, before the code merges. We recommend rolling it out
org-wide in advisory mode (it comments but never blocks), alongside a general AI reviewer
rather than instead of it.

It looks only at database access: raw SQL, migrations, `@Query` annotations, Spring Data
repository methods, and Java code that calls a repository inside a loop (the classic N+1
problem). It posts one review per PR, updated in place on every push. It never approves,
merges or edits code.

The case for it is narrow and concrete. Slow queries are invisible in a diff, they surface
months later as incidents, and a general-purpose reviewer finds them inconsistently.
QueryGuard finds a fixed set of them the same way every time, for no per-PR model cost.

The case against doing more than a pilot today is also concrete: it is early-stage, it has
been verified on a handful of real PRs, and its most ambitious half (checking queries
against a real execution plan) is not built yet.

## The problem it solves

Database performance bugs pass code review because they look fine in a diff. They fail
later, at production data volume, usually as a pager alert with no obvious cause.

- **`SELECT *` or a query with no `WHERE`.** Harmless on a 400-row test table; expensive at
  40 million rows.
- **N+1 queries.** A repository call inside a `for` loop reads as ordinary Java. Each call
  is fast. The defect is the five-thousandth repetition, and it spans two files.
- **A filter with no index behind it.** `WHERE country = ?` looks indexed until someone
  checks the migrations.
- **Unqualified writes.** `UPDATE customers SET tier = 'gold'` with no `WHERE` is a
  one-line review miss with a very large blast radius.

Reviewers are not at fault. Spotting these needs the schema, table sizes and call graph in
mind at once, on every PR. A fixed set of checks run by a machine does that more reliably
than attention does.

## How it works

A small workflow file in each repository calls QueryGuard on every pull request. Nothing
is installed on a server, and nothing leaves GitHub's runners unless the optional LLM prose
is switched on.

1. **Read the diff.** Fetch the changed files and record which exact lines the PR wrote.
2. **Extract queries.** SQL files, migrations, `@Query` annotations and Spring Data method
   names are parsed with a real SQL parser (`sqlglot`). The SQL dialect is detected from
   the repository's own datasource configuration.
3. **Apply rules.** Five deterministic rules cover unqualified writes, unbounded reads,
   filters with no index, `SELECT *` and predicates that defeat an index.
4. **Detect N+1.** Follow Java control flow across files to find repository calls made once
   per loop iteration. Whether a pattern is reported never depends on an LLM.
5. **Report only what the PR touched.** Findings in code the PR did not write are counted,
   not shown.
6. **Post one review.** Edited in place on each push. `REQUEST_CHANGES` for a blocking
   finding, `COMMENT` otherwise, never `APPROVE`.

Teams tune behaviour with a `.queryguard.yml` per repository (which severities block, which
rules only warn, which are disabled, which paths are ignored). Org-level settings outrank
repository ones. Advisory mode makes the whole thing comment-only. It fails soft: a crash
becomes a visible "could not analyze" note, not a failed or silently green check.

## Business value

The value is avoided production incidents, not faster reviews. There is no measured
incident saving yet, so this table states the mechanism and what to measure.

| Value | How QueryGuard delivers it | How to measure it |
| --- | --- | --- |
| Fewer database-driven incidents | Catches N+1 loops, unbounded reads and unqualified writes before merge | Slow-query or database-load incidents per quarter, before and after |
| Cheaper fixes | The author fixes it on the PR while the code is fresh | Time from introduction to fix |
| Consistent standard | Same checks on every PR in every repository | Findings per PR by team; share of PRs analyzed |
| Less reviewer load | Reviewers stop holding schema and call graphs in their heads | Reviewer survey after the pilot |
| Lower infrastructure cost | Avoids over-provisioning databases to absorb inefficient queries | Database CPU and replica spend |
| Auditability | Same diff gives the same findings | Spot-check replays |
| Data stays inside GitHub | With the LLM off, no code goes to a third-party model provider | Security review sign-off |

**Cost to run.** No server to host. It uses GitHub Actions minutes (a job is capped at 15
minutes) and, if enabled, a small per-PR LLM call for prose. The recurring cost is
engineering time to maintain it.

## QueryGuard vs a general AI reviewer

QueryGuard is not better than a general AI reviewer overall. A general reviewer is far
broader and will catch logic bugs, security issues and design problems QueryGuard cannot
see. QueryGuard is better at one job: finding a specific class of database problems the
same way every time, and being something you can enforce. This assumes the AI reviewer is a
general-purpose LLM review of the PR diff.

| Dimension | General AI reviewer | QueryGuard |
| --- | --- | --- |
| Scope | Any code problem | Database queries only |
| Consistency | Can differ between runs on the same diff | Same input gives byte-identical output |
| Explainability | Reasoned prose; can be confidently wrong | Named rule, file, line, evidence-strength reason |
| Cross-file N+1 | Only if the relevant files are in its context | Resolves repository types across files by design |
| Schema awareness | Only what is in the diff | Reads the repo's Liquibase schema for unindexed filters |
| Enforcement | Advisory prose | Configurable block rules, per rule and per repo |
| Per-PR cost | Model tokens on every PR | No model cost by default |
| Where code goes | To the model provider | Stays on GitHub runners unless LLM prose is enabled |
| Tuning | Prompt changes; hard to test | Per-repo config; rules tested with false-positive guards |
| Maturity | General-purpose and widely used | Early; verified on a handful of real PRs |
| Execution plans | No | Not yet; planned |

**Why both.** An LLM reviewer reads for intent and judgement. QueryGuard is a narrow,
testable gate. Where they overlap, a developer sees the same finding twice, a real cost to
measure in the pilot. If the pilot shows QueryGuard finds nothing the AI reviewer already
caught, the case weakens to enforceability and cost alone.

## Pros

- Catches a class of bugs humans miss: N+1 loops, unbounded reads, unqualified writes.
- Deterministic and testable, with each rule paired with a false-positive guard.
- No server to run: one small workflow file per repository.
- Safe by design: only ever writes its own review, never approves, never merges.
- Adoptable gradually: advisory first, then block selected rules per repository.
- Low noise by construction: only lines the PR wrote, with a reason instead of a score.
- No model cost or data sharing by default.
- Dialect-aware: MySQL, Postgres, Oracle and SQL Server detected from repository config.
- Org-level settings outrank repository ones, so a central policy cannot be quietly weakened.

## Cons, risks and limitations

**Product today**

- Early-stage; verified on a small number of real PRs from one pilot codebase. The
  false-positive rate on real traffic is not yet known statistically.
- Plan-backed analysis is not built: no `EXPLAIN` plan, no measured index impact.
- Narrow coverage: Java/Spring and SQL only. No `EntityManager.createQuery`, named queries,
  MyBatis, Flyway schemas or Kotlin. Spring Data derived methods with nested properties are
  not decoded.
- Silent misses: when it cannot decode a query it reports nothing, so "no findings" does not
  mean "no problems".
- Schema-dependent rules need a discoverable Liquibase changelog.
- Overlap with an AI reviewer: developers may see the same finding twice.

**Organizational**

- Alert fatigue: noise gets a bot muted, which is why rollout starts in advisory mode.
- Ownership: someone must own rule changes, false-positive triage and upgrades.
- Single-maintainer risk: one primary author today.
- Upgrades: repositories pin a version, so moving many repositories means many bumps unless
  managed centrally.
- Repository access: the workflow's repository visibility and Actions access must permit
  every consumer.
- No licence is declared yet.

## Rollout plan

1. **Phase 0: housekeeping.** Move the repository into the org, set visibility and Actions
   access, declare a licence, tag `v0.1.0`.
2. **Phase 1: pilot, 3 to 5 repositories, advisory mode, 3 to 4 weeks.** Exit test:
   reviewers rate most findings useful and no repository mutes the bot.
3. **Phase 2: tune.** Fix false positives, close gaps the pilot exposes, compare against the
   AI reviewer's findings.
4. **Phase 3: selective blocking.** Block on the highest-confidence rules (for example
   unqualified writes) on repositories that opt in, using branch protection.
5. **Phase 4: org-wide.** Roll out to remaining repositories with central defaults.

| Decision | Recommendation |
| --- | --- |
| Move into the org | Yes, before the pilot |
| LLM prose | Off (`disable-llm: true`) org-wide for now |
| Initial mode | Advisory for every repository |
| Pilot repositories | 3 to 5 with heavy database code |
| Maintainer and backup | Name an owner and a backup |
| Success metrics | Useful-finding rate, mute rate, incidents prevented |

**Build next, in order of value:** a plan-backed stage (real `EXPLAIN` on an isolated
database), broader Java/JPA coverage, and a central way to roll out upgrades such as a
GitHub App.
