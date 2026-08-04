# hades
It catches slow and unsafe database queries before they merge. It runs on every pull request,
analyzes SQL, JPA native queries, JPQL/HQL, and Spring Data derived methods against a real execution
plan, and posts a clear explanation with a suggested fix which is backed by measured index impact via HypoPG
and cross-query N+1 detection powered by Claude.
