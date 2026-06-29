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

Fault signature: pipeline-transformer panics at startup with
"proto: duplicate registration / incompatible protobuf runtime version" and
goes CrashLoopBackOff (pod_ready_replicas 3->0, pod_restart_total climbing to 9).
Onset is ~14:51, right after the 14:50 pipeline-transformer deploy.

Culprit = 8f1116bd26e4901475d935eb2659f8ae2273baab. Its diff bumps
google.golang.org/protobuf from v1.31.0 to v1.34.2 in pipeline-transformer/go.mod
while the module still pins github.com/golang/protobuf v1.5.2 (indirect) and
pkg/pb v0.18.0 (generated against the v1.31 runtime). The v1.34 global type
registry is incompatible with the legacy v1.5.2 registry, so init-time proto
registration panics. That is the only diff that produces this conflict. Fix:
revert the protobuf pin in go.mod/go.sum (config-revert).

Why not the near-onset decoy: defc5b0 is ALSO a "go module pins" commit on the
SAME service, committed closer to onset (14:48), and it is the commit_sha on the
14:50 deploy record -- so "blame the recent dependency bump / the deployed
commit" points there. But its diff only bumps aws-sdk-go (v1.50->v1.53), which
touches the S3 sink client and changes no protobuf/runtime dependency, so it
cannot cause the registration panic. ac4d66a (aws-sdk-go-v2 patch) is on the
root go.mod, not vendored by the transformer.

Blast radius: workflow-engine -- its pipeline-transformer endpoint returns
connection refused while the transformer pods crash-loop. It is a victim, not
the cause.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
