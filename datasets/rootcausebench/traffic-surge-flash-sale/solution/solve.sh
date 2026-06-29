#!/bin/bash
# ORACLE solution for traffic-surge-flash-sale.
# Writes the known-correct answer so we can validate the grader.
# This incident has NO guilty commit -- the correct answer is "none".
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "none",
  "first_failing_service": "frontend",
  "blast_radius": [
    "checkoutservice",
    "cartservice",
    "productcatalogservice"
  ],
  "remediation": "scale"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: traffic-surge-flash-sale (no code cause)

Answer: root_cause_commit = "none". This was an operational/external event, not a
code change.

## What broke
The alert is frontend p99 > 800ms (fired 15:06). The first service to degrade is
the edge `frontend`. In metrics.csv, frontend `requests_per_sec` climbs from
~920/s (baseline) to ~5790/s between 15:00 and 15:06 -- a ~6.3x organic surge.
Every other tier's `requests_per_sec` rises by the same ~6x in lockstep
(checkoutservice, cartservice, productcatalogservice), because the edge fans every
request out to them. Demand, not a code path, went up.

## Why it's saturation, not a bug
- `cpu_utilization` on frontend pegs near 1.0; `request_queue_depth` goes from ~0
  to 200+ once CPU crosses ~0.75. p99 crosses 800ms at 15:02 and peaks
  ~2180-2340ms. `http_5xx_per_sec` only appears AFTER CPU saturates -- that is
  load shedding (503s), not a code error.
- The slow trace spends its time as `queue_wait_ms` (~4380ms QUEUED at the edge),
  while every downstream span is normal latency (PlaceOrder ~360ms, GetProduct
  ~90ms). A code regression would show a slow span or extra work per request; here
  the hops are fine and the time is queueing.
- Logs: "worker pool saturated, request queued", "request rejected: server
  overloaded, shedding load" (503), and "autoscaler signalled desired replicas
  increase; pods pending" -- capacity lagged demand.

## Why no commit is the cause
There is NO deploy at onset. deploys.json has only three deploys, all at
14:18-14:33, well before the 15:00 surge. The tempting innocent commits:
- 8975e17f "extract request decoding into helper in frontend gateway" (frontend,
  deployed 14:21): just moves JSON decode into a helper -- same work per request.
- 4328ace9 "switch access logs to structured fields in frontend" (frontend, the
  most recent frontend deploy at 14:33): swaps log.Printf for a structured
  logger.Info -- one log line per request, not latency that scales 6x with load.
- f832d01f "bump go.mod dependencies" (gorilla/mux + grpc patch bumps,
  checkoutservice, 14:18): patch-version bumps, no behavior change.
None of these diffs produces a load-proportional saturation. The behavior is fully
explained by traffic exceeding fixed capacity. The `spring_flash_sale_banner` flag
in flags.json is a distractor.

## Remediation
Operational: scale out the frontend fleet (add replicas / let the autoscaler add
capacity) to absorb the surge. No rollback would help because no code is at fault.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
