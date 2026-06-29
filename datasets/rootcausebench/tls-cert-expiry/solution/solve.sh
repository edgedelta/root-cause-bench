#!/bin/bash
# ORACLE solution for tls-cert-expiry.
# Writes the known-correct answer so we can validate the grader.
# This incident has NO guilty commit: the trigger is an expired TLS certificate.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "none",
  "first_failing_service": "orderservice",
  "blast_radius": [
    "checkoutservice",
    "frontend"
  ],
  "remediation": "rotate-cert"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: tls-cert-expiry (no code cause -> "none")

## What broke
At 2026-06-18T15:04:00Z, orderservice outbound calls to paymentservice began
failing with `remote error: tls: x509: certificate has expired or is not yet
valid`. orderservice `upstream_call_error_ratio` jumps from ~0 to ~0.9 and it
returns 502 to its callers. The alert (orderservice-payment-call-errors) fired
at 15:07.

## The external cause is in the data
- `alert.json.detail` names the paymentservice leaf cert (CN=paymentservice.svc,
  serial 0x4f2a) with `notAfter=2026-06-18T15:04:00Z`.
- orderservice `peer certificate check ... notAfter=2026-06-18T15:04:00Z` log /
  pattern lines, and a WARN "...is expired" line at 15:04:02.
- `metrics.csv`: the paymentservice gauge `tls_cert_seconds_until_expiry` counts
  down and crosses 0 at exactly 15:04:00 -- the onset instant.
- Failing traces show the orderservice egress span `POST paymentservice/charge`
  in ERROR with `tls: x509: certificate has expired`; there is NO paymentservice
  child span, because the handshake never completes.

## Why it is "none" (no commit caused it)
Onset aligns to the certificate `notAfter` timestamp (15:04:00), NOT to any
deploy. Deploys land at 14:40:10, 14:56:30, 15:01:05, 15:03:40 and 15:06:20 --
none at 15:04:00. The cert is a managed/ops artifact; no commit in commits.json
touches a cert/key/PEM. The tempting TLS-adjacent commits are all innocent:
- 40465f54 (extract shared payment-client transport): passes the same cfg.TLS
  through unchanged -- cannot affect cert lifetime; ran clean for 24 min.
- 57d572d5 (tidy TLS cipher suite list): cipher selection is irrelevant to an
  expired-cert handshake, which fails regardless of cipher; ran clean for 8 min.
- 62590eaf (bump qtls / x/crypto patch versions): does not disable verification;
  the path still correctly reports the cert as expired (the observed behavior).
- 498ca535 (tidy PlaceOrder handler) is the innocent deploy-at-onset: it lands
  15:06:20 (after onset) and only swaps error-handling helpers; it neither does
  TLS nor predates 15:04:00.
Flags in flags.json are distractors.

## paymentservice is a healthy victim-of-perception, not the cause
paymentservice stays up (listener accepting, p99 healthy); its inbound RPS just
collapses because callers cannot complete the handshake. There is no
paymentservice code fault.

## Blast radius & remediation
First failing service: orderservice. Blast radius: checkoutservice and frontend
(they propagate the 502 / show retry banners). Remediation is operational:
rotate / reissue the paymentservice serving certificate (rotate-cert). No code
rollback fixes an expired certificate.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
