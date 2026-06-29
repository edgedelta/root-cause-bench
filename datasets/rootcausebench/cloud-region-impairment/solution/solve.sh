#!/bin/bash
# ORACLE solution for cloud-region-impairment.
# There is NO guilty commit: the trigger is an AWS S3 us-east-1 regional
# impairment (provider-side). Writes the known-correct answer ("none") so we can
# validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "none",
  "first_failing_service": "mediaservice",
  "blast_radius": [
    "catalogservice",
    "frontend"
  ],
  "remediation": "failover"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: cloud-region-impairment (no code cause -> "none")

## Fault signature
mediaservice s3_request_errors_5xx_ratio jumps from ~0 to 0.34 starting at
13:46Z and s3_request_duration_p99_ms blows out to multiple seconds. Logs are
all AWS SDK errors on calls TO S3:
  "aws sdk s3 GetObject failed: ServiceUnavailable (503) region=us-east-1
   host=edgedelta-media-prod.s3.us-east-1.amazonaws.com"
and SlowDown (503) retries. The failing trace span is `S3.GetObject` with
peer.service=aws.s3 / aws.region=us-east-1 -- the error originates INSIDE the
provider call, not in our handler code. catalogservice shows the same on
S3.ListObjectsV2. The mechanism is: the managed S3 dependency in us-east-1 is
returning 503/elevated latency, and our SDK clients fail/retry against it.

## Why no commit is the cause
status_feed.json (the cloud status dashboard) has event S3-us-east-1-2026-06-20
flipping to status="degraded" ("Increased Error Rates and Latencies") with
started_at = 13:46:00Z -- the exact onset. The same feed shows EC2 us-east-1 and
S3 us-west-2 "operating-normally". So the trigger is external/provider-side.

No deploy lines up with the 13:46 onset: media deploys are at 12:33 and 13:13,
the catalog deploy at 13:29, and the only near-onset deploy (checkoutservice
13:57) is AFTER the alert and unrelated. Decisively, checkoutservice -- which
does NOT call S3 -- stays healthy (http p99 ~210ms) through the entire window:
if any of our code had regressed broadly it would show; instead only the
S3-using services degrade, exactly when the provider feed says S3 degraded.

## Why the tempting commits are NOT the cause
- 2b8b1cd9 "tune s3 client timeouts" (ivan.petrov, services/media/s3client.go):
  only raises client RequestTimeout 3s->5s and MaxRetries 3->4. These are
  client-side knobs; they cannot make S3 itself return 503/SlowDown, and it
  deployed at 12:33 -- over an hour before onset, with healthy metrics in
  between.
- 63737f24 "extract object fetch helper" (services/media/fetch.go): pure code
  motion -- the same GetObject call moved into a helper, no behavior change.
- db5e8958 "bump go.mod": aws-sdk-go-v2 s3 v1.53.1 -> v1.53.2, a patch bump with
  no behavior change relevant to provider 503s; deployed to catalog at 13:29 and
  catalog metrics stayed clean until 13:46.
- flags media_signed_url_v2 / catalog_cache_warm are distractors.

None of these diffs can produce a provider-side 503 from S3. The answer is
"none".

## Blast radius
mediaservice is first and worst (heaviest S3 reader). catalogservice degrades on
its own S3 ListObjectsV2 calls; frontend surfaces 5xx because it depends on
mediaservice/catalogservice. These are victims of the same impaired dependency,
not causes.

## Remediation
Operational, not a rollback: fail S3 traffic over to the healthy us-west-2
region (status_feed shows us-west-2 operating-normally with a cross-region
replica) and escalate upstream to the provider. No code rollback fixes a
provider region outage. failover.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
