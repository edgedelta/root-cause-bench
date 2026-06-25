#!/bin/bash
# ORACLE solution for olapdb-tso-cas-retry-budget.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "48ad9c8a5a8caa9ee41379f17435befe8880dbc6",
  "first_failing_service": "olapdb-tso",
  "blast_radius": [
    "stream-taskmanager",
    "platform-api"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: olapdb-tso-cas-retry-budget

Culprit lowers the TSO CAS retry budget -> during TSO leader-election the FoundationDB CAS operations exhaust their (now too small) retry budget and time out -> olapdb-tso fails to issue commit timestamps -> olapdb-server CnchLock acquire times out -> the stream-taskmanager Flink taskmanager job (Metric_threshold_monitoring_job) goes unhealthy and platform-api metadata queries 5xx. Onset is ~6min delayed (budget only exhausts under leader-election churn). The dashboard-svc chart-cache deploy near onset is an innocent decoy.

Reconstructed timeline: the regression onset follows the culprit deploy. The
deploy(s) and feature-flag change closest to onset are decoys; the culprit is
the commit whose changed files directly touch the first failing service's
failing code path.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
