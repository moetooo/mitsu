"""Incremental, rate-limited catalog synchronization.

The sync package owns identity resolution, daily provider budgets, run
bookkeeping, and the idempotent refresh job. It deliberately has no scheduler
of its own: run it from cron, Task Scheduler, or `python -m app.sync.cli`.
"""

__all__ = ["run_sync"]
