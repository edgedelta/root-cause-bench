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

Cross-service / shared-library culprit. Commit 48ad9c8 edits the SHARED TSO
client library pkg/tso/client/casretry.go, lowering DefaultCASRetryPolicy
.MaxAttempts from 8 to 2 and dropping the backoff sleep. olapdb-tso links this
shared lib and was deployed at 14:30 carrying the change.

Fault signature -> diff: the trace error on olapdb-tso reads "CAS retry budget
exhausted" and the metrics tso_cas_retry_exhausted_total / fdb_txn_timeout_total
climb from 14:36. Only 48ad9c8's diff touches the CAS retry budget that this
signature names. Under TSO leader-election churn the FoundationDB CAS on the
timestamp key now exhausts its 2-attempt budget and the transaction times out ->
olapdb-tso cannot issue commit timestamps -> olapdb-server CnchLock acquire times
out -> stream-taskmanager's Flink job Metric_threshold_monitoring_job restarts and
platform-api metadata queries return 5xx. Onset (~14:36) is ~6min after the 14:30
deploy: the budget only exhausts once leader-election churn builds (delayed onset).

Why not the near-onset candidates: fdbbb04 is the LATEST deploy on the loud
failing service (olapdb-tso, 14:35, right before onset) and touches
olapdb/src/TSO/TSOServer.cpp -- but its diff is leader-election logging only
(LOG_DEBUG->LOG_INFO), causally inert. d4100be (dashboard-svc chart-cache TTL,
deployed at onset) and the tso_fast_path flag flip are unrelated distractors.
Remediation: rollback the shared-lib change (restore MaxAttempts=8).
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
