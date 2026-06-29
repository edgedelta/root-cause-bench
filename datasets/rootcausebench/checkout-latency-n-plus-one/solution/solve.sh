#!/bin/bash
# ORACLE solution for checkout-latency-n-plus-one.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "559e94ce37a7b4b6053149c40ba8a5bc9113ca6e",
  "first_failing_service": "checkoutservice",
  "blast_radius": [
    "cartservice",
    "frontend"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: checkout-latency-n-plus-one

Culprit: 559e94ce (checkoutservice, deployed 14:59:30). Its diff replaces the
denormalized cart fields with a per-line-item catalog DB lookup
(a.catalog.GetItem -> "SELECT * FROM catalog_items WHERE sku = $1") inside the
AssembleOrder loop. That is the N+1: db_query_count_per_request jumps ~3 -> ~47,
checkoutservice p99 ~210ms -> ~3800ms, productcatalogservice RPS fans out
~900 -> ~4100, and the slow PlaceOrder logs show 40-51 identical SELECTs per
request. Onset is delayed (~15:03) because the new path is only exercised under
load.

Why not the near-onset decoys:
- 78ad4135 ("refactor: tidy checkout PlaceOrder handler") is the MOST RECENT
  checkoutservice deploy before onset (15:01:25) and touches the literally-named
  PlaceOrder handler, but its diff only swaps error handling to helper funcs --
  no per-item query, so it cannot produce the DB fan-out.
- db5e56f2 is a frontend CSS restyle 30s before onset (no backend change).
- e315e6f1 is a go.mod patch-version bump. flags.json changes are distractors.

Blast radius: cartservice (times out on the slow upstream) and frontend.
productcatalogservice is a victim of the query fan-out, not the cause.
Remediation: roll back the offending deploy.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
