#!/bin/bash
# ORACLE solution for auth-jwt-validation-regression.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "7dacc6c8a3c3fe7053afd5d8518ffef1f9843baa",
  "first_failing_service": "gatewayservice",
  "blast_radius": [
    "userservice",
    "orderservice",
    "paymentservice"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: auth-jwt-validation-regression

## Fault signature
gatewayservice http_401_unauthorized_ratio sits at ~0.006 baseline, then steps up
at 10:13 and plateaus at ~0.60 (alert fires 10:21 at observed 0.61). The same 401
ramp appears, staggered by ~1-2 min, on userservice, orderservice and
paymentservice. gateway token_validation_errors_per_sec jumps from ~0 to hundreds
at 10:13. Logs across ALL four services read "jwt validation failed: token is
expired" / "rejecting request: invalid token", and traces show the auth/validation
span itself returning 401 -- on the gateway edge span AND independently on the
downstream service spans (OrderService, PaymentService). So requests are not being
forwarded-and-failed; each service is rejecting tokens locally. The mechanism is:
valid, current JWTs are being judged expired by every service at once.

## Which diff is the cause
The only thing that makes *valid* tokens expire simultaneously across services that
did not change their own code is a change to the SHARED token verifier they all
import. Commit 7dacc6c8 (carlos.mendez, 09:51) edits pkg/auth/jwt.go and removes the
clock-skew tolerance: it deletes `const leeway = 120 * time.Second` and rewrites the
expiry check from `exp.Add(leeway).Before(now)` to `exp.Before(now)`. With the 120s
leeway gone, tokens that are still valid but near expiry -- and tokens minted by pods
whose clock runs slightly ahead of the verifier -- are now rejected as expired. Every
service linking pkg/auth inherits the stricter check, which is exactly why the 401
spike is fleet-wide and not confined to one service.

The gateway was rebuilt against the new shared lib and deployed at 10:05
(version v2026.09.14-1003 in deploys.json carries 7dacc6c8). Onset is delayed ~7-8
min (10:12-10:13) because the tightened check only begins rejecting once enough live
sessions fall inside the former leeway band under load.

## Why not the tempting near-onset commit on the failing service
5116e67e (ivan.petrov, 10:09:30) touches services/gateway/middleware/auth.go on the
loud failing service, right at onset -- the obvious "blame the gateway's recent auth
commit" pick. But its diff only adds a `WWW-Authenticate: Bearer` header and changes
the 401 response body to JSON; it does not touch validation logic, so it cannot turn
valid tokens into expired ones. It also never deployed -- no deploy event carries it.

Other rejected candidates: e20445ee refactors pkg/auth/parse.go (same shared package,
scary-looking) but only extracts token parsing into a helper with no behavior change;
e51a75bd is a golang-jwt v5.2.0->v5.2.1 patch bump (no validation change); the
userservice (090d53d9) and orderservice (2e6b5b44) deploys at 10:13/10:14 are
blast-radius victims and their diffs (avatar upload, VAT rounding) are unrelated. The
gateway_strict_audience_check flag flip at 10:10 is a distractor -- the rejection
reason is expiry, not audience, and the ramp tracks the 10:05 deploy, not the flag.

## Blast radius
userservice, orderservice and paymentservice all verify tokens through the same shared
pkg/auth and start returning 401 within ~1-2 min of the gateway. They are victims of
the shared-lib change, not independent causes.

## Remediation
Roll back the build carrying the shared pkg/auth change (restore the 120s leeway /
revert 7dacc6c8). rollback.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
