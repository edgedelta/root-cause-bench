#!/bin/bash
# ORACLE solution for grpc-deadline-too-tight.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "47f38c2266850843297224b41736539a952ff546",
  "first_failing_service": "recommendationservice",
  "blast_radius": [
    "frontend"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: grpc-deadline-too-tight

Culprit: 47f38c22 (recommendationservice, deployed 14:52:30). Its diff tightens
the per-call gRPC client deadline on the productcatalog ListProducts call from
context.WithTimeout(ctx, 5*time.Second) to 300*time.Millisecond. The downstream
productcatalogservice normally answers ListProducts in ~400ms (baseline span
z4 = 401ms; incident span d1 still does ~399ms of server work; its
http_server_duration_p99_ms is ~400 in BOTH windows -- it did not get slower).
A 300ms client deadline below that normal latency makes recommendationservice's
calls hit DeadlineExceeded: rpc.grpc.status_code 4, elapsed ~305-402ms > 300ms,
rpc_client_error_rate ~0 -> ~0.61, which trips the alert ON recommendationservice.
Onset is delayed (~15:01 vs 14:52 deploy) because the tighter budget only bites
once catalog latency rises under load.

Why the noisy/obvious answers are wrong:
- productcatalogservice is the LOUD VICTIM, not the cause. It logs "context
  canceled by client before completion" (status_code 1, CANCELLED) and its
  rpc_server_cancelled_rate jumps to ~0.6 -- but only because the caller abandons
  the RPC at 300ms. Its own p99 is unchanged (~400ms). It is being cut off.
- 9a756a12 ("refactor: extract product row scanner") deploys at 15:01:10, right
  at onset, ON the service that looks broken -- the tempting bait. But its diff
  only factors scanning into scanProducts(); no timeout, no query change. It
  cannot produce DeadlineExceeded/CANCELLED.
- ea343eef ("refactor: tidy recommendation Handle path") is the MOST RECENT
  recommendationservice deploy before onset (14:59:30) and touches the named
  Recommend handler, but its diff only swaps error-handling helpers; it changes
  no deadline.
- 07a4aaf2 is a grpc dependency patch bump. flags.json changes are distractors.

Tell: the CALLER's p99 actually drops (~450ms -> ~355ms) during the incident
because it now fails fast at 300ms instead of waiting -- a tightened budget, not
a slowdown.

Blast radius: frontend (recommendation rail unavailable -> fallback).
Remediation: roll back the offending recommendationservice deploy.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
