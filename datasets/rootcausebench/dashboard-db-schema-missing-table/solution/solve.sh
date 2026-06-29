#!/bin/bash
# ORACLE solution for dashboard-db-schema-missing-table.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "4f3740c125c5a9cbcf606e020005d1fe047ba386",
  "first_failing_service": "dashboard-svc",
  "blast_radius": [],
  "remediation": "roll-forward"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: dashboard-db-schema-missing-table

Fault signature: dashboard-svc starts throwing
`sqlalchemy.exc.ProgrammingError: relation "dashboard_favorites" does not exist`
on the first request after the 11:24 deploy; http_5xx_ratio jumps from a ~0.003
baseline to 0.74.

Culprit commit 4f3740c1 ("wire up favorites endpoint") is deployed at 11:24.
Its diff adds a DAO method running `SELECT ... FROM dashboard_favorites` plus a
new /dashboard/favorites view, but ships NO migration creating that table
(files_changed are dao/dashboard.py + views/dashboard.py only). The first call
to that endpoint therefore hits a table that does not exist -> the relation
error and the 5xx spike. Remediation: ship the missing migration (roll-forward).

Why not the near-onset decoy: 451b1029 ("tweak palette tokens") deploys 30s
later, at onset, on the SAME loud service (dashboard-svc) - a tempting better
surface match. But its diff only edits frontend theme.ts color tokens and cannot
produce a database relation error. Only 4f3740c1's diff introduces the SELECT
against dashboard_favorites, so it is the cause.

Blast radius is empty: dashboard-svc fails standalone; no downstream service is
dragged down. The new_charts_ui flag flip in flags.json is a distractor.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
