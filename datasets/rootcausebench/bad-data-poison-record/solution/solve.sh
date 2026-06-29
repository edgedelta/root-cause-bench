#!/bin/bash
# ORACLE solution for bad-data-poison-record.
# Writes the known-correct answer so we can validate the grader.
# The correct answer is "none": no commit caused this incident; the trigger is
# an external/operational bad-data event.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "none",
  "first_failing_service": "event-enricher-1",
  "blast_radius": [
    "kafka-geo-events"
  ],
  "remediation": "purge-bad-data"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: bad-data-poison-record (no code cause -> "none")

## Fault signature
event-enricher-1 begins emitting a 100% `record_validation_error_ratio` at 11:38,
with the identical error on every line:

    record validation error: field 'lat' out of range [-90,90] got 412.700000;
    record_id=geo-evt-8f3a2174 partition=3 offset=148820291 producer=geo-partner-feed

The SAME record_id (`geo-evt-8f3a2174`) and SAME offset (148820291) fail over and
over (~every 7s). The consumer cannot commit past a record it cannot process, so it
redelivers that one offset indefinitely; good throughput collapses and
`kafka-geo-events` reports `geo-events-iq ApproximateAgeOfOldestMessage` climbing.

## Why this is operational, not a code change
- `lat=412.7` is an impossible coordinate (valid range [-90,90]). The validator is
  doing exactly its job by rejecting it. The bug is in the DATA, not the code.
- The bad record was produced by `producer=geo-partner-feed`, an EXTERNAL partner.
  There is no commit and no deploy for that producer anywhere in the window.
- event-enricher-1 validated good records cleanly from 10:00 through 11:36 — over a
  thousand records/2min — and the only record that fails is this single poison one.
  The code handled good records fine before and after.
- There is NO deploy at onset. The most recent deploy (v2026.06.24-1131) landed at
  11:32, and the service stayed healthy from 11:32 to onset at 11:38.

## Why each tempting commit is innocent
- `d35af7fe` "Tidy geo coordinate validation helper" deployed 11:32, right before
  onset, on the loud failing service. Its diff only refactors the lat/lon bounds
  check into a `checkRange()` helper while keeping the identical [-90,90]/[-180,180]
  limits — so it still correctly rejects lat=412.7. It does not create the bad value.
- `30cb6576` "Tidy geo record parser" is a no-behavior refactor (value->pointer,
  wrapped error). It does not touch validation or produce coordinates.
- `8e0ee5fe` "Bump geojson decoder patch" is a dependency patch bump. No diff here
  produces an out-of-range latitude.

No commit's diff produces the observed fault, and the evidence (a single repeating
offending record from an external producer, no deploy at onset) points to a bad-data
event. Therefore `root_cause_commit = "none"`.

## Blast radius and remediation
Blast radius: `kafka-geo-events` (the broker reporting the geo-events-iq backlog
downstream of the stalled consumer). Remediation: purge / quarantine the poison
record — skip offset 148820291 or move it to a dead-letter queue so the consumer can
advance — and escalate to the external producer geo-partner-feed. A code rollback
fixes nothing because no code change caused it.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
