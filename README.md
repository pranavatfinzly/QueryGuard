# QueryGuard
It catches slow and unsafe database queries before they merge. It runs on every pull request,
analyzes SQL, JPA native queries, JPQL/HQL, and Spring Data derived methods against a real execution
plan, and posts a clear explanation with a suggested fix which is backed by measured index impact via HypoPG
and cross-query N+1 detection powered by Claude.

> **Status: skeleton.** The pipeline stages are defined and typed but not yet
> implemented — each entry point raises `NotImplementedError`, and `/analyze` returns
> an empty report with `status: "not_implemented"`. What does work today: the FastAPI
> surface, the stage contracts in `queryguard/models/`, p6spy statement-log parsing,
> and the `queryguard-sandbox/` fixture app with its four planted bugs.

## Quick start

```bash
pip install -r requirements.txt
pytest                                       # no Docker or JDK needed
uvicorn queryguard.api.main:app --reload     # GET /health, POST /analyze
```

See [CLAUDE.md](CLAUDE.md) for the pipeline stages, folder layout, and conventions,
and [queryguard-sandbox/README.md](queryguard-sandbox/README.md) for the fixture app
that supplies real `EXPLAIN ANALYZE` plans and N+1 statement logs.
