---
name: migration-review
description: "Review a database migration before it runs in production. Covers lock acquisition and how long each statement holds one, the difference between a metadata lock and a row lock, adding a column with a default on a large table, backfilling in batches with a bounded window, creating an index concurrently and what happens when that fails halfway, dropping a column that application code still references, renaming in two deploys instead of one, foreign keys added as NOT VALID and validated separately, the difference between a transactional and a non-transactional migration and which engines allow which, statement timeouts as a safety net, estimating table size and row count before choosing a strategy, checking replica lag before and during, the rollback that is not actually possible once data is written, and how to stage a destructive change so that each step is independently reversible. Also covers reading the query plan after the change to confirm the index is used, verifying constraint validity, and writing the runbook entry that explains to the person on call what to do when the migration is halfway through and the deploy is rolled back."
---

# migration-review

Review a database migration before it runs in production. Covers lock
acquisition and how long each statement holds one, the difference between a
metadata lock and a row lock, adding a column with a default on a large table,
backfilling in batches with a bounded window, creating an index concurrently
and what happens when that fails halfway, dropping a column that application
code still references, renaming in two deploys instead of one, foreign keys
added as NOT VALID and validated separately, the difference between a
transactional and a non-transactional migration and which engines allow which,
statement timeouts as a safety net, estimating table size and row count before
choosing a strategy, checking replica lag before and during, the rollback that
is not actually possible once data is written, and how to stage a destructive
change so that each step is independently reversible. Also covers reading the
query plan after the change to confirm the index is used, verifying constraint
validity, and writing the runbook entry that explains to the person on call
what to do when the migration is halfway through and the deploy is rolled
back.
