#!/bin/bash
# ORACLE solution for metric-ingestor-metadata-deser.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "4e169b782276b9dd9b962e4474687622bda48589",
  "first_failing_service": "metric-ingestor-1",
  "blast_radius": [
    "kafka-metric-ingestor"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: metric-ingestor-metadata-deser

Culprit renames a metadata field on the metric envelope but the decoder still expects the old name, so deserialization fails on every message -> metric-ingestor-1 stops flushing -> the metric-ingestor-1-iq queue backs up and kafka-metric-ingestor sees rising ApproximateAgeOfOldestMessage. Rollback restores the field name. The aws-sdk bump deployed to kafka-metric-ingestor near onset is an innocent decoy.

Reconstructed timeline: the regression onset follows the culprit deploy. The
deploy(s) and feature-flag change closest to onset are decoys; the culprit is
the commit whose changed files directly touch the first failing service's
failing code path.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
