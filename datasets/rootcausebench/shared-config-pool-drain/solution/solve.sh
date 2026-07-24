#!/bin/bash
# ORACLE solution for shared-config-pool-drain.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "894bc5e29dde539c6031dba8cf092d3b399f4812",
  "first_failing_service": "paymentservice",
  "blast_radius": [
    "checkoutservice",
    "frontend"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: shared-config-pool-drain

GUILTY-LOOKING DECOY (adversarial). Culprit is the shared-library commit in pkg/dbpool/config.go: the refactor swaps a 30s AcquireTimeout duration for an int-milliseconds knob whose default is 3000 — silently shrinking the pool acquire timeout 30s -> 3s. It rides into production inside the paymentservice deploy at 09:20 (NOT the alerting service). Under the morning traffic ramp, payment db_conn_wait_ms climbs from 09:35 and acquires start failing at 3000ms ('pool acquire timeout after 3000ms' — the 3000 matches the new default). The TEMPTING answer is retry-decoy: it adds a retry loop around the exact charge RPC that is slow and deploys at 09:42, right at visible onset on the alerting service. It is exonerated twice: (1) paymentservice db_conn_wait_ms had been climbing since 09:35, before the 09:42 deploy; (2) the retry is gated on charge_retry_enabled, which flags.json shows was created OFF and never flipped, so the new code path never executes. css-decoy (frontend, 09:33) is the classic innocent-deploy-near-onset. first_failing_service is paymentservice (its DB acquires fail first); checkoutservice and frontend are blast radius. Remediation: roll back paymentservice to before the dbpool change.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
