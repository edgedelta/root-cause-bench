#!/bin/bash
# ORACLE solution for unbounded-query-delayed-onset.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "c1cba9e7f3204a8d6b59e0c1a47f28d3b6e095a7",
  "first_failing_service": "searchservice",
  "blast_radius": [
    "frontend"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: unbounded-query-delayed-onset

## Fault signature
searchservice db_query_latency_p99_ms climbs steadily and monotonically from
~40ms at 08:10 to 800ms at 10:42, crossing the 800ms threshold (alert fired
10:42:30). In lockstep, db_rows_examined jumps from ~52 to ~1.1M at 08:10 and
keeps growing to ~2.03M by 10:42, while db_cpu_pct climbs the same way. The
slow-query WARN logs show `SELECT ... FROM search_events ... ORDER BY score DESC`
with rows_examined equal to the whole tenant table, and the onset trace shows the
`db.query search_events` span at 861ms examining ~2.03M rows. This is an unbounded
full-table-scan whose cost grows with the table -- a classic delayed onset, not a
spike at deploy.

## The culprit diff
Commit c1cba9 ("order results by relevance score") was deployed to searchservice
at 08:10 -- ~2h32m before the alert. Its diff (services/search/query.go) DELETES
the `LIMIT 50` line from buildSearchSQL. Without the LIMIT, every Search() does a
full scan + sort of search_events for the tenant. Because search_events grows with
traffic, rows_examined and query latency climb steadily as the table grows, which
is exactly the observed monotonic curve. Tracing rows_examined/p99 backward, the
step from index-backed (52 rows) to full-scan (1.1M rows) happens precisely at the
08:10 deploy of this commit.

## Why not the near-onset deploy (decoy)
f7cb29d ("support sort direction in search api") is the *latest* searchservice
deploy, at 10:38 -- only ~4 minutes before the alert, which makes it the tempting
"blame the latest deploy" answer. But (1) its diff only adds an `order=asc` query
param and an in-memory `sort.Slice`, and it actually RE-ADDS a `len(res) > 50`
trim in the handler -- it touches no SQL and is bounded; and (2) p99 and
rows_examined had already been climbing steadily for ~2.5h before 10:38, so the
regression predates this deploy and cannot be caused by it. Other surface-match
decoys: c84a1f6 (pkg/dbx OrderBy refactor) reshapes the query builder but keeps the
Limit() method and changes no behavior; f27c905 raises db pool MaxConns 20->40
(adds capacity, cannot cause a per-query full scan); e16b8f4 is a rows.Close fix on
a different service. The search_relevance_v2 flag flip at 10:35 is a distractor.

## Blast radius
frontend is downstream: once searchservice query latency exceeds the frontend's
750ms upstream deadline (~10:40), the search page starts erroring ("upstream
deadline exceeded") and frontend search_page_error_ratio jumps from ~0.002 to
~0.31. frontend is a victim, not the cause.

## Remediation
Roll back searchservice to the build before c1cba9 (restoring the LIMIT 50).
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
