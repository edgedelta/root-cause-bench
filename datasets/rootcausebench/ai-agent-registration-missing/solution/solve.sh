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

Fault signature: ai-agent-svc returns HTTP 500 on the first agent lookup after
its 09:42 restart, logging "predefined internal agent lookup failed:
'thread-title-determiner' not found (org-scoped)". The startup line "agent
bootstrap complete" still prints, so the process did NOT crash — the predefined
internal agents were simply never registered into the org-scoped registry.

The 09:42 ai-agent-svc release shipped two commits. Reading the diffs:

- 41f4a783 (#ai Refactor agent bootstrap) DELETES the
  `registerPredefinedAgents(registry)` call from `bootstrapAgentRuntime()` and
  drops its import. This is exactly the mechanism: bootstrap completes, but the
  predefined agents are never seeded, so the first `getPredefinedAgent` lookup
  misses and returns 500. This is the culprit.
- 7b8e1c4a (#ai Adjust predefined-agent lookup handler) is the better SURFACE
  match — it edits the exact failing endpoint `getPredefinedAgent`. But its diff
  only adds a `scope: "org"` field to the already-existing 500 error body; it
  neither creates nor removes the registration. It is innocent.

The 09:42:20 web restyle deploy and the agent_streaming_v2 flag flip are
distractors. Blast radius: ai-memory-svc's BuildThreadContext aborts downstream
waiting on the 500ing getPredefinedAgent. Remediation: roll-forward to restore
the registration call.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
