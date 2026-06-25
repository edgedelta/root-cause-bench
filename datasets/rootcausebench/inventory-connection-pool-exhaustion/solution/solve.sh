#!/bin/bash
# ORACLE solution for inventory-connection-pool-exhaustion.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "13ac92a16b155fd29f379d4eab35ec82c976c44f",
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

Culprit lowers pgx pool max-conns (50->10) in db.yaml/pool.go. Onset is ~8 min after deploy as the pool saturates under load. The shipping + order deploys and the read_replica_routing flag near onset are decoys.

Reconstructed timeline: the regression onset follows the culprit deploy. The
deploy(s) and feature-flag change closest to onset are decoys; the culprit is
the commit whose changed files directly touch the first failing service's
failing code path. Remediation: roll back the offending deploy.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
