#!/bin/bash
# ORACLE solution for dns-resolver-degradation.
# This is a NO-CODE-CAUSE incident: the trigger is an external cluster-DNS /
# upstream-resolver degradation, not any commit. The correct answer is "none".
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "none",
  "first_failing_service": "paymentservice",
  "blast_radius": [
    "checkoutservice",
    "emailservice",
    "recommendationservice"
  ],
  "remediation": "escalate-upstream"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: dns-resolver-degradation (NO guilty commit -> "none")

## Fault signature
At 10:30 UTC, outbound calls start failing across services with NAME-RESOLUTION
errors, not application errors:
- paymentservice: "lookup api.stripe.com on 10.96.0.10:53: no such host" /
  "getaddrinfo ENOTFOUND api.stripe.com"
- checkoutservice: "lookup paymentservice.payments.svc.cluster.local ... i/o timeout"
- emailservice: "smtp send failed: lookup smtp.sendgrid.net ... no such host"
- recommendationservice: "lookup featurestore.ml.svc.cluster.local ... i/o timeout"

These four services are UNRELATED and resolve four DIFFERENT hostnames, yet they
all begin failing within ~1 minute of 10:30. No single application commit can
cause four independent services to fail to resolve four different names at the
same instant. paymentservice trips its monitor first (10:41) and is the
first_failing_service; the other three are the blast radius.

## The external cause is visible
- metrics.csv, service=coredns, step exactly at 10:30:
  coredns_servfail_ratio ~0 -> 0.5+, coredns_request_duration_p99_ms ~15ms ->
  ~5000ms, coredns_forward_healthcheck_failures 0 -> >0.
- coredns logs: "plugin/forward: all upstreams down; returning SERVFAIL" and
  "forward: HEALTHCHECK: read udp ...->169.254.20.10:53: i/o timeout".
- status_feed.json: cluster-DNS (CoreDNS) / upstream resolver "degraded" at
  10:30, multiple namespaces affected, infra paging the upstream DNS provider.
The resolver itself is broken; our services are healthy except that they cannot
resolve hostnames on egress.

## No deploy at onset
deploys.json has only three deploys, all well BEFORE onset (09:18 paymentservice,
09:46 checkoutservice, 10:02 emailservice). Nothing deployed at or near 10:30.
A code regression would line up with a deploy; this does not.

## Why each tempting commit is NOT the cause
- 94e921a6 (pkg/httpclient/client.go, "unify outbound http client"): only
  retunes http.Transport idle-connection settings (MaxIdleConns,
  IdleConnTimeout). It does not touch DNS resolution or any hostname. Connection
  pooling has nothing to do with getaddrinfo failing.
- 2f6d5580 (deploy/config/endpoints.yaml, "tidy service-discovery config"):
  regroups and reformats the endpoint config; the hostnames are byte-for-byte
  identical before and after. No resolution behavior changes.
- 4f9b40d3 (go.mod, "bump dependencies"): grpc v1.62.0 -> v1.62.1 patch bump, no
  resolver behavior change.
Feature flags (checkout_new_pricing_ui, recs_ann_index_v2) are distractors.

## Conclusion + remediation
No commit's diff produces cluster-wide name-resolution failure. The cause is the
upstream/cluster DNS resolver degrading. root_cause_commit = "none". Remediation
is operational: escalate to the upstream DNS provider and/or fail CoreDNS forward
over to a secondary resolver. No code rollback would fix it. (escalate-upstream)
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
