#!/bin/bash
# ORACLE solution for ai-agent-registration-missing.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "41f4a783a75e53ab9bd5169adaeb2b0413d0d339",
  "first_failing_service": "ai-agent-svc",
  "blast_radius": [
    "ai-memory-svc"
  ],
  "remediation": "roll-forward"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: ai-agent-registration-missing

Culprit refactors agent bootstrap and drops the step that registers predefined internal agents (e.g. thread-title-determiner) at startup. After the deploy/restart the org-scoped lookup can't find them and ai-agent-svc returns 500; ai-memory-svc's context builder fails downstream. Fix is to restore the registration (roll-forward), matching the real fallback-fix PR. The web restyle deploy near onset is an innocent decoy.

Reconstructed timeline: the regression onset follows the culprit deploy. The
deploy(s) and feature-flag change closest to onset are decoys; the culprit is
the commit whose changed files directly touch the first failing service's
failing code path.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
