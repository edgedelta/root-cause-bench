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

GUILTY-LOOKING DECOY (adversarial, v3 — de-fingerprinted, derived-evidence proof). Culprit is the shared-library commit in pkg/dbpool/config.go: the refactor swaps a 30s AcquireTimeout duration for an int-milliseconds knob whose default is 3000 — silently shrinking the pool acquire timeout 30s -> 3s. It rides into production inside the paymentservice deploy at 09:20 (NOT the alerting service). v3 removes the verbatim string fingerprint that let a solver grep its way to the answer: the payment ERROR log now reads 'db conn acquire failed: context deadline exceeded while waiting for a free connection' (no digits at all), and the paymentservice 'Charge db.acquire' trace-span error is now 'context deadline exceeded' (also no digits) — neither agent-visible text string quotes 3000 anywhere. The literal '3000' now appears in exactly one place in environment/data: inside the culprit commit's own diff in context/commits.json (`cfg.Int("db.pool_timeout_ms", 3000)`), which is the mechanism itself, not a leaked fingerprint. Proof must instead be built from DERIVED, cross-signal evidence: (1) db_conn_wait_ms ramps from 09:35 (onset) to a plateau of ~3050ms (jitter 0.08) that holds for the rest of the window — a numeric ceiling a solver must read off the metric, not quote from a log; (2) two independent trace exemplars corroborate the same ~3.0s ceiling across separate incident timestamps: paymentservice 'Charge db.acquire' spans of duration_ms 3001 (09:47:10) and 3004 (09:52:40), both erroring 'context deadline exceeded' with no duration mentioned in the error text itself; (3) only then does connecting ~3000ms observed to the culprit diff's `cfg.Int("db.pool_timeout_ms", 3000)` ms-units default require genuine inference (recognizing that AcquireTimeout moved from a *Duration constructed via `30*time.Second`* to a raw int now interpreted as *milliseconds*, so the new default is 3s, not 30s) — this is causal reasoning, not string equality. Timing alone still does not exonerate anything — six innocent/decoy commits deploy in the 47 minutes straddling onset, plus 16 auto-generated background deploys across all three services, so every exoneration below is mechanism-based, not schedule-based. retry-decoy (checkoutservice, 09:26, PRE-onset) adds a retry loop around the exact charge RPC that is slow; it is exonerated purely by mechanism: the retry path is gated on charge_retry_enabled, which flags.json shows was created OFF at 08:55 and never flipped, so the new code path never executes regardless of when it deployed. deadline-raise (checkoutservice, 08:50) touches the very file/RPC that times out, but only *raises* the client deadline 2s->5s — it cannot manufacture a pool-acquire timeout and if anything would mask one, not cause it. prepared-statements (paymentservice, 09:05) touches the payment DB layer that fails, but only adds a statement cache lookup around an existing PrepareContext call — it cannot shrink or touch the pool's acquire-timeout setting. histogram-decoy (paymentservice, 09:12, deployed 8 minutes before the real culprit and to the SAME service) is the most mechanism-plausible decoy in this scenario: it touches pool-adjacent code (wraps the acquire call) and even its histogram name ('db_pool_acquire_wait') echoes the failure mode. It is nonetheless exonerable purely by mechanism: the diff only adds a `time.Now()`/`Observe()` timer around the existing `r.pool.Acquire(ctx)` call and records a metric — it reads the pool's behavior, it does not configure the pool, and it changes no timeout, no config key, no default. css-decoy (frontend, 09:33, pre-onset) and csv-bump-decoy (checkoutservice, 09:47, within 3 min of fired_at 09:50) are classic innocent-deploy-near-alert bait with trivially unrelated diffs (CSS spacing; an export page-size constant). The 16 deploys_auto entries (>=6 pre-onset, cyclic over the three services) are pure background noise: routine dependency bumps, doc/test/CI tweaks, none touching dbpool, retry, or the payment pool. Patterns.json is also noisier: checkoutservice's WARN pattern (8/min) and frontend's ERROR pattern (6/min) are louder than paymentservice's connection-failure ERROR pattern (kept at 4/min, still present, just no longer the loudest signal), and three stale unrelated negative patterns (kafka rebalancing, disk usage, TLS renewal — counts 45-78, delta +2, pre-existing background chatter) sit below all three incident patterns. A frontend asset_cache_miss_ratio spike (0.04 -> 0.4, 08:20-08:50) self-heals well before onset and is unrelated noise. first_failing_service is paymentservice (its DB acquires fail first); checkoutservice and frontend are blast radius. Remediation: roll back paymentservice to before the dbpool change.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
