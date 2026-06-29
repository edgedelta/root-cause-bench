#!/bin/bash
# ORACLE solution for cache-ttl-stampede.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "c62e9decee7bb083f3628909019dd66e25dd25d8",
  "first_failing_service": "productdb",
  "blast_radius": [
    "catalogservice",
    "frontend",
    "searchservice"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: cache-ttl-stampede

## Fault signature
The page is on productdb: db_cpu_utilization sits at ~24% through 13:12, climbs
steadily, crosses the 85% threshold around 13:36, and pins at ~94-96% from ~13:41.
db_query_duration_p99_ms and db_queries_per_second rise with it, and productdb logs
fill with "slow query: SELECT * FROM catalog_items WHERE id=$1" and
"statement timeout ... under load". So the DB is being overrun by read volume.

But the DB itself did not change. The discriminating metric is
cache_hit_ratio on catalogservice: it holds at ~0.97 through 13:12 and then
bleeds DOWN to ~0.55 over the following ~25 minutes. db_queries_per_second is
inversely tied to it (qps ~165 -> ~700): every cache miss is a read-through to
productdb. The mechanism is a cache stampede -- the cache stopped absorbing
reads, so the backing DB got the full read load.

## Which deploy, which commit
The only thing that changes at the start of the hit-ratio decline is the
catalogservice deploy at 13:12, shipping commit c62e9dec. Its diff lowers the
SHARED read-through cache DefaultTTL in pkg/cache/config.go (and redis.yaml)
from 15 * time.Minute to 15 * time.Second. catalogservice embeds that shared
cache and does not set its own TTL, so after the deploy every catalog_item entry
expires in 15s. The onset is DELAYED ~24 min because the already-warm entries
keep serving hits until their original 15m TTL elapses; only as they expire does
the hit ratio collapse and the DB saturate. This is a cross-service cause: the
failing/paged service is productdb, but the causal code lives in a platform-owned
shared cache library and was authored by the caching team (priya.sharma).

## Why not the tempting near-onset commits
- 9ecb8232 (tomas.novak, db team) is a productdb migration deployed at 13:38,
  immediately before the 13:46 page and ON the loud service. But its diff only
  adds an index CONCURRENTLY on catalog_items.updated_at. Adding an index cannot
  quadruple read CPU, and it is on updated_at while the slow query is an id=$1
  point lookup. It is the bait, not the cause.
- a9b8c7e4 (carlos.mendez, catalogservice, 13:31) refactors the catalog lookup
  handler and touches cache.GetOrLoad, so it looks cache-related, but the diff
  only collapses an if/return -- no behavior change.
- d642c0cd merely adds cache hit/miss counters. The orderservice deploy
  (a5b4c3e0) and the catalog_query_planner_v2 flag flip at 13:37 are distractors.

## Blast radius
catalogservice latency rises because every miss waits on the overloaded DB;
frontend and searchservice call catalogservice and hit their 1500ms upstream
timeout. These are victims, not the cause.

## Remediation
Roll back the cache deploy -- revert the shared DefaultTTL to 15m (or pin
catalogservice's TTL explicitly). rollback.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
