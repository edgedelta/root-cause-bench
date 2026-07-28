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

BEYOND-CONTEXT / MONOREPO (adversarial, v3 — cache-adjacent decoy candidates, cardinality-only discrimination). 307 commits over 73h; ~24MB of telemetry across logs/metrics/traces/patterns — the data cannot be read whole, it must be sliced. Culprit is the mid-history pkg/cache/key.go commit (deployed to catalogservice 2026-07-19T02:40Z, ~30h before the alert): adding req.SessionID to the catalog cache key explodes key cardinality, so cache_hit_ratio decays from 0.97 toward 0.31 and redis_mem_mb ramps 240->3900 starting at 2026-07-19T03:00Z (right after that deploy), while catalog_latency_p99_ms only breaches threshold on 07-20 as the DB fallback saturates — a very long delayed onset. v3 deepens the candidate set so the culprit can no longer be found by 'only one diff touches the cache' — there are now FOUR key/cache-touching catalogservice changes pre-dating onset (env-prefix-decoy 2026-07-18T22:00Z, ttl-raise-decoy 2026-07-19T01:30Z, redis-decoy 2026-07-19T02:00Z, culprit 02:40Z), and the hit-ratio decay + redis_mem_mb ramp only begin at 03:00 — after ALL FOUR deploys, so timing exonerates none of them. The culprit must be found by CARDINALITY reasoning: which change actually multiplies the key space? env-prefix-decoy ('namespace cache keys by environment', deployed 2026-07-18T22:00Z) edits the SAME FILE as the culprit (pkg/cache/key.go) and looks like the smoking gun — but its diff only prepends a static const `"prod:"` prefix to the key format string; a constant prefix is cardinality-neutral, one extra fixed token cannot multiply the key space or move a hit ratio. ttl-raise-decoy ('raise catalog cache TTL', deployed 2026-07-19T01:30Z, services/catalog/cache.go) triples TTL from 10m to 30m; a longer TTL retains entries LONGER, which can only increase hit ratio, and a 3x TTL bump cannot explain a 16x memory blowup (240->3900MB) or a hit-ratio collapse to 0.31 — the direction of the change is wrong. redis-decoy ('tune redis client timeouts', deployed 2026-07-19T02:00Z, about an hour before the 03:00 onset) is exonerated purely by mechanism too: lowering a ReadTimeout from 500ms to 400ms cannot decay a hit ratio or grow memory footprint. Only the culprit's diff adds a per-request/per-session dimension (req.SessionID) to the key itself, which is the one change that actually multiplies cardinality; the comment on that diff has been softened to 'scope cache entries to the request context' so the mechanism must be read from the code (the added req.SessionID field), not announced by the prose. redis-lib-bump ('bump redis client lib 8.4.1->8.4.3', catalogservice, deployed 2026-07-18T20:00Z) is a changelog-free go.mod version bump with no logic change, exonerated by mechanism. cache-warm-on-boot ('warm popular-page cache on boot', catalogservice, deployed 2026-07-19T14:00Z, squarely mid-decay) looks maximally relevant — a cache change landing while cache_hit_ratio is actively decaying — but its diff only pre-populates a handful of popular-page keys via the same CatalogKey helper on startup; it adds hits, it cannot explain a hit-ratio *decay* driven by per-session key cardinality, and it does not touch key construction. dashboard-decoy (08:32) remains the innocent-position deploy near the alert (fired_at 08:40). 28 deploys_auto entries (18+ pre-onset, cyclic across all 8 services) are pure background noise: routine dependency/docs/CI/test tweaks, none touching cache keys, redis, or catalog. Patterns are victim-first: frontend's new WARN ('product page render slow: catalog upstream 900ms', 8/min from 2026-07-20T03:00Z) is the loudest negative pattern, ahead of catalogservice's own cache-miss WARN (6/min from 2026-07-20T04:00Z through window end so it doesn't out-count the victim); 4 stale patterns_extra (pool-warmup retries, disk usage, TLS renewal, kafka rebalancing; counts 42-80) are unrelated background chatter across other services, well below both incident patterns. A shippingservice label_api_latency_ms spike (baseline ~85 -> 340, 2026-07-19T21:00-22:00Z) self-heals well before onset and is unrelated noise on an uninvolved service. Monorepo: route changes by files_changed paths (services/<svc>/, pkg/, go.mod), not by service-named repos. Remediation: roll back catalogservice to before the cache-key change.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
