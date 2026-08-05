# queryguard-sandbox

A deliberately flawed Spring Boot application, used as a fixture for QueryGuard.

**This is not a reference implementation.** It contains four planted performance
bugs and one destructive query. Do not copy patterns out of it, and do not point
it at any database you care about.

## Layout

```
src/main/java/com/queryguard/sandbox/
├── SandboxApplication.java
├── domain/          Customer, Order, OrderItem, OrderStatus
├── repository/      CustomerRepository, OrderRepository, OrderItemRepository
├── service/         ReportingService, MaintenanceService
└── seed/            DataSeeder (JavaFaker)
src/main/resources/
├── application.properties
└── db/migration/V1__create_tables.sql
```

## Schema

`customers` 1—N `orders` 1—N `order_items`, with `ON DELETE CASCADE` down the
chain.

Index coverage is deliberate. `orders.customer_id`, `orders.placed_at`,
`orders.status`, `order_items.order_id`, and `customers.signed_up_at` are
indexed; `customers.email` is uniquely indexed. **`customers.country` is
intentionally left unindexed** — it is the target of planted bug 2. Do not add an
index for it.

## Planted bugs

Each is marked in source with a `PLANTED BUG:` comment.

| # | Bug | Location | Caught by |
| - | --- | -------- | --------- |
| 1 | Native query, `SELECT *`, no `WHERE` | `OrderRepository.exportAllOrders` | Static rules + `EXPLAIN ANALYZE` (seq scan) |
| 2 | JPQL filtering an unindexed column (`country`) | `CustomerRepository.findByCountryCode` | `EXPLAIN ANALYZE` + HypoPG index suggestion |
| 3 | Derived method called inside a `for` loop (N+1) | `ReportingService.buildCustomerOrderSummary` | LLM cross-query stage + p6spy statement log |
| 4 | `UPDATE` with no `WHERE` | `CustomerRepository.promoteAllToTier` | Static rules (critical) |

Each bug sits next to a healthy counterpart so the rules can be tested for false
positives as well as true ones — `exportRecentOrders`, `findBySignedUpAtAfter`,
`buildCustomerOrderSummaryBatched`, and `promoteHighValueCustomers` respectively.
QueryGuard should flag the first column and stay silent on the second.

### Bug 4 is destructive and guarded

`promoteAllToTier` rewrites `loyalty_tier` for every row in `customers` and holds
a row lock on the whole table for the transaction. Its only call site,
`MaintenanceService.promoteLoyaltyTier`, throws unless
`sandbox.allow-destructive-fixtures=true`, which defaults to `false`. QueryGuard
analyzes source, so the fixture works without ever executing. Enable the flag
only against a database you are willing to lose.

## Seed data

`DataSeeder` runs on startup (`sandbox.seed.seed-on-startup`, default `true`) and
skips if `customers` is already populated. Defaults produce ~5,000 customers,
~20,000 orders, and ~60,000 items on a fixed random seed (`20260805`), so plan
fixtures are reproducible.

Distributions are skewed rather than uniform, because uniform data hides the
problems QueryGuard looks for — with even spread the planner's estimates are
always right and a missing index costs almost nothing:

- **Orders per customer** — heavy tail: ~28% never order, most place 1–4, a small
  VIP cohort places up to ~40. Row estimates for a customer join are therefore
  wrong for the tail.
- **Country** — weighted, US-dominant (40% US, 4% JP). A `country` predicate is
  highly selective for `JP` and barely selective for `US`, so the missing index
  shows very different costs per bind value.
- **Order status** — weighted toward `DELIVERED` (62%).
- **`placed_at`** — recency-weighted across 18 months; orders never predate signup.
- **Prices** — log-normal, with a thin tail of expensive items.

## Running it

Requires a JDK 21+ and Maven, plus a local Postgres. There is no Maven wrapper
checked in — generate one with `mvn -N wrapper:wrapper` if you want `./mvnw`.

```bash
# Throwaway database
docker run --rm -d --name queryguard-sandbox-db \
  -e POSTGRES_DB=queryguard_sandbox \
  -e POSTGRES_USER=queryguard \
  -e POSTGRES_PASSWORD=queryguard \
  -p 5432:5432 postgres:16

mvn spring-boot:run
```

Flyway applies `V1__create_tables.sql` on boot, then the seeder fills the tables.

## Known dependency wrinkle

JavaFaker 1.0.2 (last released 2020) calls `new SafeConstructor()`, a no-arg
constructor SnakeYAML 2.x removed. Spring Boot 3.x manages SnakeYAML to 2.x, so
`pom.xml` pins `snakeyaml.version` back to `1.33`; config lives in
`application.properties` rather than `.yml` so Boot itself never needs SnakeYAML.
[Datafaker](https://www.datafaker.net/) is the maintained fork with the same API
if you would rather drop the pin — JavaFaker is used here because it was asked
for by name.
