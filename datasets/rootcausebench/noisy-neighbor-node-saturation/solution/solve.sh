#!/bin/bash
# ORACLE solution for noisy-neighbor-node-saturation.
# This incident has NO guilty commit: the trigger is operational (a noisy
# neighbor saturating the shared node). The known-correct answer is "none".
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "none",
  "first_failing_service": "recommendationservice",
  "blast_radius": [
    "frontend",
    "checkoutservice"
  ],
  "remediation": "reschedule"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: none (noisy-neighbor node saturation)

## Fault signature
recommendationservice http_server_duration_p99_ms steps from ~78ms to ~4200ms
starting at 13:40 and breaches the 500ms monitor at 13:48. The discriminating
signal is NOT in our service: container_cpu_cfs_throttled_seconds for
recommendationservice jumps from ~0.02 to ~8.9 over the same window, while the
service's own http_requests_per_second stays FLAT at ~42 rps and its
container_cpu_usage_cores is pinned at the cgroup quota (it is being throttled,
not doing more work). So the mechanism is CPU starvation imposed from outside
the process, not a code-level slowdown and not a load increase.

## The external trigger (why "none")
Node-level metrics for gke-prod-pool-3-a1b2 show node_cpu_utilization_ratio
climbing 0.34 -> 0.97 and node_memory_utilization_ratio 0.41 -> 0.93, beginning
EXACTLY at 13:40:00. The kube-scheduler log at 13:40:00 records:
"Scheduled pod analytics/analytics-batch-export-29kd7 to node
gke-prod-pool-3-a1b2" -- an unrelated batch/cron pod from the analytics
namespace landing on the SAME node as recommendationservice-7c9f-q4m2. The
neighbor's container_cpu_usage_cores ramps to ~5.6 and
container_memory_working_set_gib to ~11.2. kubelet then emits NodeUnderPressure,
CPUThrottlingHigh (naming recommendationservice), and MemoryPressure events.
Our pod degrades purely by co-location. Onset aligns to the neighbor's
scheduling, NOT to any deploy.

## Why no commit is the cause
recommendationservice's only changes in the window deployed BEFORE onset and
none can produce node-wide CPU/memory saturation or cgroup throttling:
- d4b8e1a6 (13:02, deployed 13:05): refactor extracting the ranking scorer into
  a helper -- behavior-preserving, no extra allocation or loops.
- 0e7c3a9f (13:19, deployed 13:22): config bump candidate_cache_entries
  50000 -> 60000. A 20% cache-size bump cannot saturate a node's CPU, and the
  latency step is at 13:40 (~18 min later), not at 13:22.
- f2a8c6e0: prometheus/client_golang 1.19.0 -> 1.19.1 patch bump, no behavior
  change.
The flags (recommendation_rerank_v2 13:21, checkout_suggestions_enabled 12:30)
are distractors and predate onset. No commit's diff implements the observed
mechanism, so the answer is root_cause_commit = "none".

## Blast radius
frontend (GET /api/home) and checkoutservice (GET /api/checkout/suggestions)
call recommendationservice for ranking; their requests time out after 1500ms on
the starved ranking calls (frontend error_rate_5xx_ratio and checkoutservice
p99 both climb after 13:40). They are victims, not the cause.

## Remediation
Operational, not a code rollback: reschedule -- evict the analytics batch pod
off the node (or add pod anti-affinity / a resource limit so a co-tenant cannot
saturate the shared node), or scale recommendationservice onto an uncontended
node. Rolling back our service would not help because no code is at fault.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
