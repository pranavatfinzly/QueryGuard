"""Reference-database concerns: provisioning and transaction management.

Stage 4 of the pipeline lives here rather than under ``pipeline/`` because these
two invariants are database-wide, not stage-specific: the database is always
isolated (:mod:`.provision`) and nothing ever commits (:mod:`.session`).
"""
