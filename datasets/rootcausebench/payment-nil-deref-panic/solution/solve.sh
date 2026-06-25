#!/bin/bash
# ORACLE solution for payment-nil-deref-panic.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "5642d6b17f39cc430c2a48ca705cbab33002d03b",
  "first_failing_service": "paymentservice",
  "blast_radius": [
    "checkoutservice",
    "frontend"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: payment-nil-deref-panic

Culprit dereferences an optional 3DS field without a nil check; panic on every charge. checkout and frontend are downstream victims.

Reconstructed timeline: the regression onset follows the culprit deploy. The
deploy(s) and feature-flag change closest to onset are decoys; the culprit is
the commit whose changed files directly touch the first failing service's
failing code path. Remediation: roll back the offending deploy.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
