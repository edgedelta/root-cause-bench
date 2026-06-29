#!/bin/bash
# ORACLE solution for inventory-connection-pool-exhaustion.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "c7d2e9a3f1b04658e8a72c0d9b5e34176af2c801",
  "first_failing_service": "inventoryservice",
  "blast_radius": [
    "cartservice",
    "shippingservice",
    "frontend"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: inventory-connection-pool-exhaustion

## Fault signature
inventoryservice db_pool_wait_seconds_p99 crosses 0.5s and explodes to ~10s by
13:50. The discriminating metric is db_pool_max_conns: it steps 50 -> 10 at
13:42:00, and db_pool_in_use then saturates exactly at the new ceiling of 10
from 13:50 onward. Logs/traces show "pgx pool: context deadline exceeded
acquiring connection (pool exhausted)". So the mechanism is: the connection
pool's maximum size was lowered, and under normal load the pool saturates,
queueing acquires until they time out. Onset is DELAYED ~8 min after the deploy
because the smaller pool only saturates once enough concurrent reservations
arrive.

## Which deploy, which commit
The inventory deploy at 13:42 lines up exactly with the max_conns 50->10 step.
That deploy ships commit c7d2e9a3, which changes the SHARED db client library
pkg/db/pool.go and lowers `const defaultMaxConns = 50` to `= 10`. inventoryservice
does not override MaxConns, so it inherits the lowered shared default. This is a
cross-service cause: the failing service is inventory, but the causal code change
lives in a platform-owned shared library and was authored by the platform team
(carlos.mendez), not the inventory team.

## Why not the tempting near-onset commit on the failing service
1a6f4b9c (ivan.petrov, 13:18) touches services/inventory/db/pool.go and
config/db.yaml -- it is on the failing service and looks like the obvious pool
change. But its diff only raises MaxConnIdleTime (30s -> 5m) and HealthCheckPeriod
(15s -> 60s). Neither lowers the max-conns ceiling, so it cannot produce the
db_pool_max_conns 50->10 step or the saturation at 10. It is an innocent change to
the same file family.

Other rejected candidates: 6e19c5ce bumps pgx v5.5.4 -> v5.5.5 (a patch bump, no
behavior change to the ceiling); the shipping (ba9484ce) and order (76005bb9)
deploys near onset are downstream victims / unrelated; the
inventory_read_replica_routing flag flip is a distractor.

## Blast radius
cartservice and frontend call inventoryservice for reservations and time out
waiting on the exhausted pool (5000ms upstream timeouts); shippingservice quotes
are dragged down through the same path. These are victims, not the cause.

## Remediation
Roll back the inventory deploy (revert the shared pkg/db default to 50, or pin
inventory's MaxConns explicitly). rollback.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
