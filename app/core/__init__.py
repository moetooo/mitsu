"""Shared primitives that neither `sync` nor `ingestion` may own.

These three modules used to live in `app.sync`, which made `app.ingestion`
depend on `app.sync` while `app.sync` already depended on `app.ingestion`
(ARCH-02). Nothing in here imports either package, so both can depend on
`app.core` and the dependency points one way: `sync -> ingestion -> core`.

* `budget`   -- per-provider daily request quotas, read from the database clock.
* `identity` -- external-id normalisation and attachment to a catalog row.
* `schema`   -- read-only schema readiness check and the id backfill.
"""
