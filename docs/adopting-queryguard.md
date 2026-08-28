# Adopting QueryGuard in another repository

QueryGuard's pipeline reads a pull request entirely over the GitHub API (diff,
changed files, schema discovery, cross-file N+1 resolution) — it never needs a
local checkout of the repository it is reviewing. That makes adoption a small,
repository-local piece of CI configuration, not a shared service anything has
to be pointed at. This works identically for public and private repositories;
the one thing that differs between them is how fork pull requests are handled
(below).

**What it actually looks at.** QueryGuard analyzes raw SQL (`.sql` files,
migrations), JPQL/HQL (`@Query`), JPA native queries
(`@Query(nativeQuery = true)`, `createNativeQuery`), and Spring Data derived
query methods, in Java sources — today's target is a Java/Spring Boot
repository, optionally with a Liquibase-managed schema. Adding the workflow
below to a repository in a different stack is harmless (it will simply find
nothing to extract, and every run reports clean) but won't produce useful
findings.

## Add it to a repository

Create `.github/workflows/queryguard.yml` in the consumer repository:

```yaml
name: QueryGuard
on:
  pull_request:
    types: [opened, synchronize]

concurrency:
  group: queryguard-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    uses: pranavatfinzly/QueryGuard/.github/workflows/queryguard-review.yml@main
    permissions:
      contents: read
      pull-requests: write
    # secrets: is optional — omit the whole block if you have no GROQ_API_KEY.
    secrets:
      groq-api-key: ${{ secrets.GROQ_API_KEY }}
```

The snippet above omits `with:` entirely — every one of its inputs
(`liquibase-changelog-path`, `groq-model`, `block-severities`, `pr-number`)
is optional, so leave the block out unless you have a specific reason to set
one, e.g.:

```yaml
    with:
      liquibase-changelog-path: src/main/resources/db/changelog.xml
```

That is the whole integration. Nothing else needs installing, vendoring, or
checking out.

**Pin `@main` to a tag or commit SHA once QueryGuard cuts a release.** `@main`
is fine while iterating solo; a repo that isn't yours (or that you want to
stop babysitting) should pin, the same reason you'd pin any third-party
Action.

**Sanity-check it locally before wiring it into CI (optional but recommended).**
This catches most configuration mistakes — a missing token scope, an
unreachable Liquibase path — in seconds, without waiting on an Actions run or
posting anything:

```bash
pip install "git+https://github.com/pranavatfinzly/QueryGuard.git@main"
export GITHUB_TOKEN=ghp_...   # a token with at least read access to the repo
queryguard review --repo OWNER/REPO --pr NUMBER --dry-run
```

`--dry-run` reads the real pull request and runs the full pipeline, but never
posts anything — it just prints the report and the enforcement decision
(`PASS`/`BLOCKED`/`DEGRADED`/`FAILED`) to your terminal. Drop `--dry-run` only
once you're ready for it to actually post.

## Required and optional configuration

| What | Where it's set | Required? |
| --- | --- | --- |
| GitHub token | Automatic (`secrets.GITHUB_TOKEN`) | Always present, nothing to configure — see the permissions note below, though |
| `GROQ_API_KEY` | Repo or org **secret** ([Settings → Secrets and variables → Actions → New repository secret](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions)), passed through as shown above | Optional — unset means N+1 findings are reported without LLM-authored prose, everything else is unaffected |
| `LIQUIBASE_CHANGELOG_PATH` | `with:` input | Optional — auto-discovered from the repo's own `db.liquibase.change-log` declaration; only needed for a non-standard or ambiguous layout |
| `QUERYGUARD_BLOCK_SEVERITIES` | `with:` input | Optional — defaults to `CRITICAL,HIGH` blocking (`REQUEST_CHANGES`); everything else posts as `COMMENT` |

No fork of QueryGuard, no copy of its source, no per-repo Python environment
to maintain — every consumer always runs whatever `queryguard-ref` resolves
to (a tag once one exists, `main` today).

## Verifying it worked, and the most common first-run failure

Open (or push to) a pull request in the consumer repository, then check two
places: the **Actions** tab for a "QueryGuard" run, and the pull request's
**Reviews** for one from the token's identity (`github-actions[bot]` for the
default token) whose body starts with a hidden `<!-- queryguard:review -->`
marker. A second push updating that same review in place, rather than adding
a new one, confirms the idempotency is working too.

**The failure you are most likely to hit on a first setup:** the job runs,
QueryGuard produces real findings, and the very last step fails with
`403: Resource not accessible by personal access token` (or similarly,
"Resource not accessible by integration"). This means QueryGuard analyzed the
pull request correctly but could not submit its review — the automatic token
didn't have write access to pull requests, even though the workflow's own
`permissions:` block asks for it. The workflow's `permissions:` block is a
ceiling, not a guarantee: a repository (or organization) can restrict the
default `GITHUB_TOKEN` below what any individual workflow requests. Check
**Settings → Actions → General → Workflow permissions** and make sure it is
not locked to "Read repository contents permission" — either set it to "Read
and write permissions", or, if your organization enforces the read-only
default, add an explicit exception for this workflow. (The same failure shows
up if you run `queryguard review --post-comment` locally with a personal
access token that lacks "Pull requests: Read and write" for the target
repository — same fix, different settings page: the token's own repository
permissions, not the repo's Actions settings.)

## Making a blocking finding actually block the merge

Adding the workflow above is not, by itself, enough to stop a bad pull
request from merging. QueryGuard submits a `REQUEST_CHANGES` review when a
finding meets the blocking threshold (`CRITICAL`/`HIGH` by default) and exits
its CI job with a non-zero status — but it never touches branch protection,
never merges, and never closes anything (CLAUDE.md's own invariant). Whether
either of those signals actually stops the merge button is entirely a
property of the consuming repository's branch protection settings, not
something QueryGuard controls. On a repo with no branch protection at all, a
`REQUEST_CHANGES` review is advisory: anyone with write access can merge past
it.

To make it a real gate, configure branch protection on the target branch
(**Settings → Branches → Branch protection rules**) with one or both of
these — most repositories want both:

1. **Require approvals.** Under "Require a pull request before merging",
   enable "Require approvals" (1 is enough). With this on, an outstanding
   `REQUEST_CHANGES` review — QueryGuard's or a human's — genuinely disables
   the merge button until it is resolved: either QueryGuard clears it on a
   later run (pushing a fix and re-triggering `synchronize` makes it re-post
   its own review, moving to `COMMENT` if nothing blocking remains), or
   someone with permission dismisses the review manually. Caveat: a repo
   admin can still bypass this unless "Do not allow bypassing the above
   settings" is also checked, and dismissing QueryGuard's review is always
   possible for anyone with that permission — this lever is a policy nudge,
   not a hard wall.
2. **Require status checks to pass.** Under "Require status checks to pass
   before merging", mark the QueryGuard job (`review`, from the workflow
   above) as required. `queryguard review` exits `2` when the run is
   `BLOCKED`, `1` when QueryGuard itself could not reliably analyze the pull
   request, `3` on misconfiguration, and `0` for `PASS`/`DEGRADED` — so a
   blocking finding fails the CI check itself, independent of the review
   mechanism above. This is the harder-to-accidentally-bypass gate, and the
   one most teams should treat as the actual enforcement point.

Without at least one of these configured, QueryGuard is purely advisory:
useful information on the pull request, but nothing stops a merge.

## The one thing that differs: public repos and fork pull requests

A pull request from a **branch of the same repository** works exactly the
same on public and private repos: the workflow's `permissions:` block
(`pull-requests: write`) grants the automatic token enough access to post
QueryGuard's review, and that is true regardless of visibility.

A pull request from an **external fork** — common on public repositories,
essentially never seen on private ones — is different. GitHub deliberately
issues a **read-only** `GITHUB_TOKEN` to a workflow triggered by
`pull_request` from a fork, no matter what the `permissions:` block asks for.
QueryGuard still runs and still produces a report (fail-soft, per its own
invariants) but the final `--post-comment` step cannot create the review, and
the run fails with a permissions error from the GitHub API.

If a public repository needs QueryGuard to review fork PRs, switch the
trigger from `pull_request` to `pull_request_target`:

```yaml
on:
  pull_request_target:
    types: [opened, synchronize]
```

This is safe specifically because QueryGuard never checks out or executes the
fork's code — every read goes through the GitHub API at the PR's head SHA,
and the only thing installed is QueryGuard itself from its own trusted repo.
`pull_request_target` is dangerous when a workflow checks out the fork's ref
and then runs something from it (a build step, a test suite); QueryGuard does
neither, so that risk doesn't apply here. Restricting `on:` this way is
still worth doing deliberately, not by default — treat it as a per-repository
decision, not something to blanket-apply.

## What this does not (yet) give you

A GitHub App installation model — install once at the organization level,
every current and future repo covered automatically, no per-repo workflow
file — does not exist yet; today's model is one small workflow file per
repository, which is deliberately the simpler thing to ship first. If
QueryGuard ends up covering many repositories across an org, that is the
natural next step (`api/routes/webhooks.py` in the architecture already
reserves the shape for it), but it is not required for "any repo, public or
private" today — the workflow-call model above already covers that.
