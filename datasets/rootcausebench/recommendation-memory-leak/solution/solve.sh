#!/bin/bash
# ORACLE solution for recommendation-memory-leak.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "c6566fcc695be384caeebd7ae0a893ccb345ae83",
  "first_failing_service": "recommendationservice",
  "blast_radius": [
    "frontend"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: recommendation-memory-leak

Culprit caches per-request scores in a package-level map that never evicts -> unbounded growth -> OOMKill ~12 min after deploy. The 'prefetch goroutine' commit deployed near onset is a plausible decoy but is not the leak.

Reconstructed timeline: the regression onset follows the culprit deploy. The
deploy(s) and feature-flag change closest to onset are decoys; the culprit is
the commit whose changed files directly touch the first failing service's
failing code path. Remediation: roll back the offending deploy.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
