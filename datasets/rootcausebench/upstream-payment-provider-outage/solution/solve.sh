#!/bin/bash
# ORACLE solution for upstream-payment-provider-outage.
# This incident has NO guilty commit. Writes the known-correct answer ("none")
# so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "none",
  "first_failing_service": "paymentservice",
  "blast_radius": [
    "checkoutservice"
  ],
  "remediation": "failover"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: upstream-payment-provider-outage (no code cause)

Answer: root_cause_commit = "none". No commit in the window produces the observed
fault; the trigger is an external third-party payment provider (Stripe) outage.

## What is actually broken
- alert: paymentservice charge_error_rate_pct above 5% (observed 71.4%) at 11:18.
- Every paymentservice ERROR log is on the OUTBOUND provider call:
  "POST https://api.stripe.com/v1/charges returned 503" / "... exceeded deadline"
  (upstream.host=api.stripe.com). Our own request handling is fine.
- metrics: paymentservice upstream_provider_error_rate_pct rises 0.x% -> ~73% over
  11:05–11:15 and recovers by 11:27, exactly tracking charge_error_rate_pct.
  paymentservice requests_per_sec is FLAT ~300 the whole time -> NOT a traffic surge.
- traces: the slow/erroring span is the single outbound HTTP POST to
  api.stripe.com/v1/charges (peer.service=stripe, http.status_code=503) plus its
  retries. There is exactly ONE charge call per request -> NOT an N+1 fan-out.

## The external signal
status_feed.json (Stripe status): the Charges API component is "partial_outage";
api_error_rate_pct for api.stripe.com/v1/charges jumps 0.5 -> 12.7 at 11:04, peaks
~73% at 11:10, recovers by 11:27 — the same window as our symptom. The provider is
down on its side; our calls to it 5xx.

## Why none of the tempting commits is the cause
- f0a2b4c6 "refactor: tidy payment Charge handler" is the MOST RECENT paymentservice
  deploy, landing at 11:05:30 right at onset — but its diff only swaps error handling
  to decodeRequest/writeError helpers. It changes no provider call, so it cannot make
  api.stripe.com return 503.
- b6c8d0e2 "refactor: extract chargeRequest builder" is a pure extract-method; the
  exact same params are sent to the provider.
- c7d9e1f3 "chore: tune payment client retry settings" raises MaxAttempts 2->3 and
  backoff. More retries against an already-degraded provider add load; they do not
  cause the provider's 5xx (and the retries themselves 503 in the traces).
- e3f5a7b9 "chore: bump go.mod dependencies" bumps the stripe-go SDK v76.21.0->v76.22.0,
  a client-library patch bump that cannot change the provider's server-side availability.
- flags.json (payment_new_receipt_layout, ledger_async_writeback) are distractors.

## Blast radius and remediation
checkoutservice calls paymentservice and times out / surfaces "upstream paymentservice
charge unavailable" -> it is a victim, not the cause. cartservice stays healthy.
Remediation is operational: fail over to the secondary/backup payment provider (or
escalate to the upstream provider) and ride out the outage. No code rollback can fix
a third-party provider outage.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
