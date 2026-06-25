#!/bin/bash
# ORACLE solution for dynamodb-write-capacity-breach.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "a1af4c1adbefc965050848b55ef37e7f0edd4987",
  "first_failing_service": "ai-memory-svc",
  "blast_radius": [
    "ai-agent-svc"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: dynamodb-write-capacity-breach

Culprit removes write batching (BatchWriteItem) in the memory store, so every memory write becomes an individual PutItem. Per-item write volume multiplies, consumed write capacity climbs over ~8min and breaches the provisioned write-capacity ceiling on DynamoDB table memory-store -> ProvisionedThroughputExceededException -> ai-memory-svc write failures; ai-agent-svc can't persist thread memory. Rollback restores batching. Two innocent deploys (platform-api access-log, web banner) and a feature-flag flip near onset are decoys.

Reconstructed timeline: the regression onset follows the culprit deploy. The
deploy(s) and feature-flag change closest to onset are decoys; the culprit is
the commit whose changed files directly touch the first failing service's
failing code path.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
