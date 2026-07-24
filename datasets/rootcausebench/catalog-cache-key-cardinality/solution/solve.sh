#!/bin/bash
# ORACLE solution for catalog-cache-key-cardinality.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "6795b1e12d8268ced328643112337d68a27bb784",
  "first_failing_service": "catalogservice",
  "blast_radius": [
    "frontend"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: catalog-cache-key-cardinality

BEYOND-CONTEXT / MONOREPO (adversarial, v2 — pre-culprit decoy, dense deploys, victim-first patterns). 305 commits over 73h; ~24MB of telemetry across logs/metrics/traces/patterns — the data cannot be read whole, it must be sliced. Culprit is the mid-history pkg/cache/key.go commit (deployed to catalogservice 2026-07-19T02:40Z, ~30h before the alert): adding req.SessionID to the catalog cache key explodes key cardinality, so cache_hit_ratio decays from 0.97 toward 0.31 and redis_mem_mb ramps 240->3900 starting at 2026-07-19T03:00Z (right after that deploy), while catalog_latency_p99_ms only breaches threshold on 07-20 as the DB fallback saturates — a very long delayed onset. Timing alone no longer exonerates anything here: redis-decoy ('tune redis client timeouts', catalogservice, deployed 2026-07-19T02:00Z) now deploys BEFORE the culprit (02:40) and about an hour before the 03:00 decay/mem-growth onset — the classic 'most-recent-catalogservice-change' heuristic would implicate it first. It is exonerated purely by mechanism: lowering a redis client ReadTimeout from 500ms to 400ms cannot decay a hit ratio or grow memory footprint — both the decay and the mem ramp start at 03:00, strictly after BOTH the redis-decoy deploy (02:00) and the culprit deploy (02:40), so a reader must inspect the diff, not the clock, to clear it. redis-lib-bump ('bump redis client lib 8.4.1->8.4.3', catalogservice, deployed 2026-07-18T20:00Z, ~6.5h before redis-decoy) is the classic dependency-bump suspect sitting closest in time and service to the incident's earliest visible cause; its diff is a changelog-free go.mod version bump with no logic change, so it is exonerated by mechanism too. cache-warm-on-boot ('warm popular-page cache on boot', catalogservice, deployed 2026-07-19T14:00Z, squarely mid-decay) looks maximally relevant — a cache change landing while cache_hit_ratio is actively decaying — but its diff only pre-populates a handful of popular-page keys via the same CatalogKey helper on startup; it adds hits, it cannot explain a hit-ratio *decay* driven by per-session key cardinality, and it does not touch key construction. dashboard-decoy (08:32) remains the innocent-position deploy near the alert (fired_at 08:40). 28 deploys_auto entries (18+ pre-onset, cyclic across all 8 services) are pure background noise: routine dependency/docs/CI/test tweaks, none touching cache keys, redis, or catalog. Patterns are victim-first: frontend's new WARN ('product page render slow: catalog upstream 900ms', 8/min from 2026-07-20T03:00Z) is the loudest negative pattern, ahead of catalogservice's own cache-miss WARN (6/min from 2026-07-20T04:00Z through window end so it doesn't out-count the victim); 4 stale patterns_extra (pool-warmup retries, disk usage, TLS renewal, kafka rebalancing; counts 42-80) are unrelated background chatter across other services, well below both incident patterns. A shippingservice label_api_latency_ms spike (baseline ~85 -> 340, 2026-07-19T21:00-22:00Z) self-heals well before onset and is unrelated noise on an uninvolved service. Monorepo: route changes by files_changed paths (services/<svc>/, pkg/, go.mod), not by service-named repos. Remediation: roll back catalogservice to before the cache-key change.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
