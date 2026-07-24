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

BEYOND-CONTEXT / MONOREPO (adversarial). 303 commits over 73h; ~12MB of telemetry — the data cannot be read whole, it must be sliced. Culprit is the mid-history pkg/cache/key.go commit (deployed to catalogservice 2026-07-19T02:40Z, ~30h before the alert): adding req.SessionID to the catalog cache key explodes key cardinality, so cache_hit_ratio decays from 0.97 toward 0.31 and redis_mem_mb ramps 240->3900 starting right after that deploy, while catalog_latency_p99_ms only breaches threshold on 07-20 as the DB fallback saturates — a very long delayed onset. redis-decoy ('tune redis client timeouts', catalogservice, deployed 08:15) is the guilty-looking near-onset change on the right service, but hit-ratio decay predates it by ~29h and its diff only lowers a client read timeout. dashboard-decoy (08:32) is the innocent-position deploy. Monorepo: route changes by files_changed paths (services/<svc>/, pkg/), not by service-named repos. Remediation: roll back catalogservice to before the cache-key change.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
