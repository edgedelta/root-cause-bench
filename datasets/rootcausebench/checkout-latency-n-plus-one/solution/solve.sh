#!/bin/bash
# ORACLE solution for checkout-latency-n-plus-one.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "559e94ce37a7b4b6053149c40ba8a5bc9113ca6e",
  "first_failing_service": "checkoutservice",
  "blast_radius": [
    "cartservice",
    "frontend"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: checkout-latency-n-plus-one

Culprit adds a per-line-item catalog lookup (N+1). The frontend CSS deploy 30s before onset is a decoy. productcatalogservice is a victim of fan-out, not the cause.

Reconstructed timeline: the regression onset follows the culprit deploy. The
deploy(s) and feature-flag change closest to onset are decoys; the culprit is
the commit whose changed files directly touch the first failing service's
failing code path. Remediation: roll back the offending deploy.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
