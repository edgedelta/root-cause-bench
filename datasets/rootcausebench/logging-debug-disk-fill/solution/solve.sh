#!/bin/bash
# ORACLE solution for logging-debug-disk-fill.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "ce164c13c54ed0cb3bc6d2e28545adc9e2656641",
  "first_failing_service": "logging-agent",
  "blast_radius": [
    "log-query-api",
    "ingest-gateway"
  ],
  "remediation": "config-revert"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: logging-debug-disk-fill

Fault signature: at the 10:00 deploy of logging-agent, log_write_throughput_lps
jumps from ~1200 to ~12000 lines/sec while a flood of DEBUG records appears in
the logs. disk_used_pct on /var/log/edge climbs steadily from ~0.42 and reaches
1.0 by ~10:18. Immediately after, write_error_count spikes and the agent logs
"no space left on device", then "filesystem mounted read-only", then the writer
goroutine exits. The disk-pressure monitor fires at 10:25 (observed 100%).

Cause: commit ce164c13 ("chore: tune logging-agent runtime config defaults")
changes services/logging-agent/config/agent.yaml: logging level info->debug and
sample_rate 0.1->1.0. That is exactly the change that produces a 10x write
amplification and fills the disk. Reading the diff, not the message, is what
identifies it -- the message is innocuous.

Why not the near-onset decoy d270fbb ("refactor: extract sink writer helper"):
it is on the SAME failing service and touches the sink writer (a better surface
match by file/service), and it deployed just before onset -- but its diff only
extracts a writeLine() helper with identical OpenFile/Write/Close behavior. It
changes no log level, sampling, or volume, so it cannot fill the disk.

Blast radius: log-query-api reads the same /var/log/edge volume and starts
returning read-only-filesystem errors; ingest-gateway buffers to capacity when
the agent sink goes unavailable. Both are victims, not the cause.

Feature-flag change agent_gzip_sink (10:06) is a distractor.

Remediation: revert the config change (config-revert).
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
