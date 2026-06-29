#!/bin/bash
# ORACLE solution for dynamodb-write-capacity-breach.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "7e2c9b41a0f5d3c8b6e4f10927ad3c5e8f1b6a04",
  "first_failing_service": "ai-memory-svc",
  "blast_radius": [
    "ai-agent-svc"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: dynamodb-write-capacity-breach

## Fault signature
ai-memory-svc throws DynamoDB ProvisionedThroughputExceededException on table
memory-store. metrics.csv shows dynamodb_consumed_write_capacity flat at the 320
baseline until 17:12, then climbing ~200/min (360, 560, 760 ... 1960) and pinning
at the 2400 provisioned ceiling from 17:23 on, while dynamodb_write_throttle_ratio
ramps from ~0.004 to 0.58. The WARN lines from 17:12:30 onward —
"single-item PutItem to memory-store (batching disabled); consumed write capacity
rising" — name the mechanism: writes that used to be batched are now per-item, so
each write consumes its own capacity unit and the table saturates.

## Timeline
- baseline: ai-memory-svc logs "batched N memory writes ... (BatchWriteItem)";
  consumed capacity flat at 320, throttle ratio ~0.004.
- 17:12:00 deploy v2026.06.22-1712 of ai-memory-svc ships commit 7e2c9b41.
- 17:12:30 onset: single-item PutItem WARN lines begin; capacity starts climbing
  (~8 min delayed-onset ramp as load accumulates against the provisioned ceiling).
- 17:20:10 first ProvisionedThroughputExceededException ERRORs; ai-agent-svc
  starts logging "memory persist failed: ai-memory-svc returned 503".
- 17:23:00 monitor fires at throttle ratio 0.58.

## Why 7e2c9b41 (the shared lib), not the tempting near-onset changes
The ai-memory-svc deploy at 17:12 carries commit 7e2c9b41 to the SHARED
persistence library pkg/memstore/dynamo_writer.go. Its diff replaces the
BatchWriteItem grouping loop (<=25 items per request) with a per-item PutItem
loop. That is exactly the batched -> per-item change the WARN lines and the
linear capacity ramp describe. ai-memory-svc's own code did not change in a way
that touches the write path.

Decoys:
- a1af4c1 (17:08, ai-memory-svc internal/compaction/compact.go) is the most
  recent commit ON the failing service and touches its own files, but it only
  tweaks turn-summarization logic and cannot change DynamoDB write volume.
- c036... (platform-api request-id middleware) and ff6268... (web banner CSS)
  deploy at ~17:19, right at onset, but neither touches the memory write path.
- the feature-flag flip memory_compaction_v2 off->on at 17:19:10 is a distractor.

## Blast radius
ai-agent-svc is downstream: it gets 503s persisting thread memory because
ai-memory-svc's writes are throttled. It is a victim, not the cause.

## Remediation
Rollback the ai-memory-svc deploy (revert 7e2c9b41) to restore BatchWriteItem
batching; consumed write capacity drops back under the provisioned ceiling.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
