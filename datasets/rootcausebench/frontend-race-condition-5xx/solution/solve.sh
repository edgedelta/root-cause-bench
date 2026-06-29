#!/bin/bash
# ORACLE solution for frontend-race-condition-5xx.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "c3a79d0eaeeded2803a3f2b24c9fb7ae7825a560",
  "first_failing_service": "frontend",
  "blast_radius": [
    "cartservice"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: frontend-race-condition-5xx

Culprit: c3a79d0e (frontend, committed 14:54:40, deployed 14:55:30). Its diff
removes the `sync.Mutex` (`mu`) field from the rate-limiter `Limiter` struct and
deletes the `l.mu.Lock()` / `defer l.mu.Unlock()` pair guarding the shared
`counts` map write (`l.counts[clientID]++`) in `(*Limiter).Allow`. That leaves a
concurrent, unsynchronized write to a Go map -- a data race that makes the Go
runtime throw `fatal error: concurrent map writes` whenever two requests hit
`Allow` at the same time.

Fault signature -> diff:
- Logs show `fatal error: concurrent map writes` with
  goroutine_stack = `runtime.mapassign_faststr -> frontend/middleware.(*Limiter).Allow(ratelimit.go:38)`.
  That is exactly the map write the culprit unlocked.
- Error traces on POST /api/checkout fail in ~6-12ms with
  `panic recovered: concurrent map writes` -- a crash, not slow latency.
- `http_server_5xx_rate` is ~0 until ~15:02 then spikes; it tracks
  `requests_per_sec` and is intermittent (dips at 15:09 while RPS still rises).
  Classic load-correlated race: harmless right after the 14:55 deploy, only
  fires once concurrency is high enough (onset ~15:02).

Why not the near-onset decoys:
- 30432f5f ("refactor: tidy frontend checkout handler") is the MOST RECENT
  frontend deploy (15:01:40, right at onset) and touches the checkout handler
  and a 502 path -- a great surface match for "5xx on checkout". But its diff
  only swaps error handling to `decodeRequest`/`writeError` helpers; it adds no
  shared-map write and removes no lock, so it cannot cause "concurrent map
  writes". The panic stack points at ratelimit.go, not handler.go.
- 7547b550 is a chi/grpc patch-version go.mod bump (no concurrency change).
- b81fa784 (frontend access-log middleware) was committed 15:21 / deployed
  15:22 -- AFTER onset -- so it cannot be the cause.
- flags.json (frontend_new_recommendation_rail) is a distractor.

Blast radius: cartservice logs "upstream frontend reset connection during
checkout" and its 5xx/p99 rise only after frontend's. productcatalogservice
stays flat. Remediation: roll back the c3a79d0e frontend deploy to restore the
lock.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
