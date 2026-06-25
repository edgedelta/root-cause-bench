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

Culprit ships DAO/view code that SELECTs from a dashboard_favorites table, but the corresponding migration was omitted, so the table does not exist -> dashboard-svc 500s with 'relation does not exist'. Fix is to add the missing migration (roll-forward). The color-palette deploy near onset is an innocent decoy; the right SHA is the migration/DAO commit, not the theme commit.

Reconstructed timeline: the regression onset follows the culprit deploy. The
deploy(s) and feature-flag change closest to onset are decoys; the culprit is
the commit whose changed files directly touch the first failing service's
failing code path.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
