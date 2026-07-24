#!/bin/bash
# ORACLE solution for notification-buffer-oom-silent.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "f9f358d2b02e04c3a6fadaafacc3715535446980",
  "first_failing_service": "notification-svc",
  "blast_radius": [
    "workflow-engine",
    "platform-api"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: notification-buffer-oom-silent

DEGRADED TELEMETRY / SILENT FAILING SERVICE (adversarial, v2 — pre-onset decoys, dense deploys). notification-svc's own logs STOP at onset 09:40 (the process OOMs; its logging dies with it) — there is not a single notification-svc log line after onset, and that absence is the primary clue; there is likewise no healthy notification-svc span in any post-onset trace. Culprit is the batch-webhook-dispatch commit (deployed 08:40): it replaces the bounded drop-on-full channel with an unbounded batch slice, so under a consumer backlog dispatch_queue_depth and container_memory_rss_mb ramp from 08:40 until the 4GB OOMKill at 09:40 (rss flat-lines, container_restarts steps to 7, CrashLoopBackOff). Peers tell the story: workflow-engine spams 'connection refused to notification-svc:8080' from 09:40 (8/min) and platform-api enqueue errors follow at 09:44 (5/min). Timing alone no longer exonerates anything here — 14 auto-generated background deploys land across the three services (>=5 pre-onset), plus two authored innocents deploy in the hour before onset, so every exoneration below is mechanism-based. workflow-decoy (workflow-engine, now deployed 09:20, PRE-onset) is the most dangerous bait: the workflow-engine connection-refused errors literally START right after its deploy (09:40 onset, 20 minutes later), making it look causal and it owns the alerting service besides. It is exonerated purely by mechanism: its diff only enriches an existing error-log line with `err.Error()` — it cannot manufacture a downstream connection-refused condition — and the notification-svc rss ramp that actually explains the outage began at 08:40, a full 40 minutes before workflow-decoy even deployed. keepalive-decoy ('perf(notify): tune webhook client keepalive', notification-svc, deployed 09:10) is the scariest suspect of all: right service, pre-onset, deployed squarely mid-ramp while memory is already climbing. It is exonerated because the ramp's START (08:40) predates its 09:10 deploy by 30 minutes, and its diff touches only the HTTP client's MaxIdleConns/IdleConnTimeout keepalive settings — orthogonal to the unbounded batch-slice growth that actually drives the OOM. first_failing_service is notification-svc even though it is silent. Patterns: workflow-engine's connection-refused ERROR (8/min) stays the loudest negative pattern; platform-api's enqueue-failure ERROR is louder than before (5/min, up from 3) but still second; notification-svc contributes zero fault patterns (its logs died with it); 3 `[[patterns_extra]]` stale background negatives (kafka consumer lag on billing-worker, disk usage on auth-gateway, TLS renewal on search-indexer; counts 48-74, delta +2) sit below both incident patterns, unrelated pre-existing chatter on uninvolved services. Noise: jitter of 0.05 on container_memory_rss_mb and 0.2 on notification_dispatch_error_ratio; a workflow-engine step_retry_count spike (baseline ~2 -> 46) from 07:00-07:30 self-heals a full two hours before onset and is unrelated red-herring noise. Remediation: roll back notification-svc to the bounded-queue build.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
