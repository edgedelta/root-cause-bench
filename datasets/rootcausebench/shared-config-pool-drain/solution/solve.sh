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

GUILTY-LOOKING DECOY (adversarial, v2 — pre-onset decoys, dense deploys, noisy telemetry). Culprit is the shared-library commit in pkg/dbpool/config.go: the refactor swaps a 30s AcquireTimeout duration for an int-milliseconds knob whose default is 3000 — silently shrinking the pool acquire timeout 30s -> 3s. It rides into production inside the paymentservice deploy at 09:20 (NOT the alerting service). Under the morning traffic ramp, payment db_conn_wait_ms climbs from 09:35 (onset) and acquires start failing at 3000ms ('pool acquire timeout after 3000ms' — the 3000 matches the new default). Timing alone no longer exonerates anything here — five innocent commits deploy in the 40 minutes straddling onset, plus 16 auto-generated background deploys across all three services, so every exoneration below is mechanism-based, not schedule-based. retry-decoy (checkoutservice, 09:26, now PRE-onset) adds a retry loop around the exact charge RPC that is slow; it is exonerated purely by mechanism: the retry path is gated on charge_retry_enabled, which flags.json shows was created OFF at 08:55 and never flipped, so the new code path never executes regardless of when it deployed. deadline-raise (checkoutservice, 08:50) touches the very file/RPC that times out, but only *raises* the client deadline 2s->5s — it cannot manufacture a pool-acquire timeout and if anything would mask one, not cause it. prepared-statements (paymentservice, 09:05) touches the payment DB layer that fails, but only adds a statement cache lookup around an existing PrepareContext call — it cannot shrink or touch the pool's acquire-timeout setting. css-decoy (frontend, 09:33, pre-onset) and csv-bump-decoy (checkoutservice, 09:47, within 3 min of fired_at 09:50) are classic innocent-deploy-near-alert bait with trivially unrelated diffs (CSS spacing; an export page-size constant). The 16 deploys_auto entries (>=6 pre-onset, cyclic over the three services) are pure background noise: routine dependency bumps, doc/test/CI tweaks, none touching dbpool, retry, or the payment pool. Patterns.json is also noisier: checkoutservice's WARN pattern (8/min) and frontend's ERROR pattern (6/min) are louder than paymentservice's pool-timeout ERROR pattern (kept at 4/min, still present, just no longer the loudest signal), and three stale unrelated negative patterns (kafka rebalancing, disk usage, TLS renewal — counts 45-78, delta +2, pre-existing background chatter) sit below all three incident patterns. A frontend asset_cache_miss_ratio spike (0.04 -> 0.4, 08:20-08:50) self-heals well before onset and is unrelated noise. first_failing_service is paymentservice (its DB acquires fail first); checkoutservice and frontend are blast radius. Remediation: roll back paymentservice to before the dbpool change.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
