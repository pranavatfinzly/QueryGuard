"""QueryGuard pipeline modules.

One module per pipeline stage. See CLAUDE.md for the stage order and the
constraints each stage must honour (isolated reference DB, BEGIN/ROLLBACK,
fail-soft behaviour).
"""
