"""Incremental, rate-limited catalog synchronization.

The sync package owns run bookkeeping, guardrails and the idempotent refresh
job, driving the provider clients in `app.ingestion`. It deliberately has no
scheduler of its own: run it from cron, Task Scheduler, or `python -m app.sync.cli`.

Identity resolution, daily provider budgets and the schema readiness check live
in `app.core`, not here: `app.ingestion` needs all three and must not import
this package (ARCH-02). The dependency points one way -- `sync -> ingestion ->
core` -- and `tests/test_layering.py` enforces it.
"""

__all__ = ["run_sync"]
