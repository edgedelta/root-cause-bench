#!/bin/bash
# ORACLE solution for transformer-dependency-startup-crash.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "8f1116bd26e4901475d935eb2659f8ae2273baab",
  "first_failing_service": "pipeline-transformer",
  "blast_radius": [
    "workflow-engine"
  ],
  "remediation": "config-revert"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: transformer-dependency-startup-crash

Culprit bumps the protobuf runtime in pipeline-transformer/go.mod, creating a runtime version conflict (duplicate registration / incompatible runtime) that panics on startup -> pipeline-transformer CrashLoopBackOff -> workflow-engine's pipeline-transformer endpoint is unavailable. The fix is to revert the dependency change (config-revert of go.mod/go.sum). TRAP: an innocent '#deps Bump aws-sdk minor' deployed to workflow-engine near onset is a decoy — it is a dependency bump too, but it touches a different service and does not cause the protobuf panic. The right SHA is the pipeline-transformer protobuf bump, not the aws-sdk bump.

Reconstructed timeline: the regression onset follows the culprit deploy. The
deploy(s) and feature-flag change closest to onset are decoys; the culprit is
the commit whose changed files directly touch the first failing service's
failing code path.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
