#!/bin/bash
# ORACLE solution for metric-ingestor-metadata-deser.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "ab35071b2e727961bb1efeb7fd8e6d73d8f7c088",
  "first_failing_service": "metric-ingestor-1",
  "blast_radius": [
    "kafka-metric-ingestor"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: metric-ingestor-metadata-deser

The fault signature is a 100% deserialize-error ratio on metric-ingestor-1 with
the error "missing required field 'meta'" beginning ~10:59, after which the
service stops flushing to olapdb and the metric-ingestor-1-iq queue backs up
(kafka-metric-ingestor reports rising ApproximateAgeOfOldestMessage).

This is a cross-service version-skew bug in a SHARED library. The shared schema
module commit ab35071b renames the metric-envelope field `meta` -> `metadata`
(both the json struct tag and the required-fields list in envelope_gen.go). The
producer pipeline-transformer bumps that shared module to v0.9.0 (commit
1f0d0d35) and deploys at 10:52, so it starts emitting envelopes keyed
`metadata`. metric-ingestor-1 still links the old schema and its strict decoder
requires `meta`; every message therefore fails to deserialize.

Why not the near-onset deploys:
- 4e169b78 is an innocent refactor on metric-ingestor-1 itself, deployed at
  10:57 right at onset (the tempting "latest deploy on the loud service").
  Its diff only restructures decoder construction; it does not touch field names.
- 1f0d0d35 is only the go.mod bump that pulls the shared module in; the breaking
  change lives in ab35071b, not in the bump.
- 17f8bae4 is an aws-sdk-go-v2 patch on kafka-metric-ingestor, unrelated.

Blast radius: kafka-metric-ingestor (queue-age backlog downstream of the stalled
consumer). Remediation: roll back the shared schema module / producer to the
version that still emits `meta`.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
