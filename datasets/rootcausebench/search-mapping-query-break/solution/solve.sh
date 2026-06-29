#!/bin/bash
# ORACLE solution for search-mapping-query-break.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "4074a93cbf3be1458094e636f38d7f2fa8d4d29b",
  "first_failing_service": "searchservice",
  "blast_radius": [
    "frontend",
    "recommendationservice"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: search-mapping-query-break

Culprit: 4074a93c (searchservice, deployed 14:59:50). Its diff in
services/search/index/mapping.go renames the indexed catalog field
"title" -> "name" in CatalogMapping, but the query builder in
services/search/query.go is left unchanged, still issuing
NewMatchQuery("title", ...). Once the new mapping goes live, every search
targets a field that no longer exists in the mapping, so the engine returns
query_shard_exception / parse_exception: "no mapping found for field [title]".

Fault signature:
- search_error_rate_pct: ~1% -> ~94% (alert: >5% for 3m, fired 15:06)
- search_result_count_avg: ~14 -> ~0
- p99 DROPS ~200ms -> ~70ms (queries fail fast; this is NOT a latency/N+1 bug)
- logs/traces: "no mapping found for field [title]" / "unknown field [title]",
  query.field="title", result_count=0
Onset is delayed (~15:03) vs the 14:59:50 deploy: errors only surface once the
new mapping is live and the path is queried under load.

Why not the near-onset decoys:
- 2a2f3891 ("refactor: tidy search handler request decoding", searchservice) is
  the MOST RECENT searchservice deploy before onset (15:01:40) and touches the
  literally search-named handler.go -- but its diff only swaps inline request
  decoding/error handling for decodeSearchRequest/writeError helpers. It changes
  no field name and no mapping, so it cannot produce "no mapping found for field".
- f91ebd4b is a frontend search-box CSS/template restyle (no backend/query change).
- 714a570c is a go.mod patch bump (opensearch-go v2.3.0->v2.3.1, grpc) -- no query
  or mapping change. flags.json changes are distractors.

Blast radius: frontend (search bar returns 5xx) and recommendationservice
(similar-items lookup fails) are victims of the searchservice errors, not the cause.
Remediation: roll back the offending mapping deploy.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
