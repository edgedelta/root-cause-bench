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

DEGRADED TELEMETRY / SILENT FAILING SERVICE (adversarial). notification-svc's own logs STOP at onset 09:40 (the process OOMs; its logging dies with it) — there is not a single notification-svc log line after onset, and that absence is the primary clue. Culprit is the batch-webhook-dispatch commit (deployed 08:40): it replaces the bounded drop-on-full channel with an unbounded batch slice, so under a consumer backlog dispatch_queue_depth and container_memory_rss_mb ramp from 08:40 until the 4GB OOMKill at 09:40 (rss flat-lines, container_restarts steps to 7, CrashLoopBackOff). Peers tell the story: workflow-engine spams 'connection refused to notification-svc:8080' from 09:40 and platform-api enqueue errors follow at 09:44. The TEMPTING answer is workflow-decoy — workflow-engine is the loudest service, it owns the alert, and it deployed at 09:52, six minutes before the alert fired; but its diff only enriches an error-log message, and the connection-refused errors predate its deploy by 12 minutes. first_failing_service is notification-svc even though it is silent. Remediation: roll back notification-svc to the bounded-queue build.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
