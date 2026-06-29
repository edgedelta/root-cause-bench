#!/bin/bash
# ORACLE solution for recommendation-memory-leak.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{
  "root_cause_commit": "c6566fcc695be384caeebd7ae0a893ccb345ae83",
  "first_failing_service": "recommendationservice",
  "blast_radius": [
    "frontend"
  ],
  "remediation": "rollback"
}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: recommendation-memory-leak

## Fault signature
recommendationservice container_memory_rss_mb climbs steadily and monotonically
from ~216MB at 08:25 to ~500MB by 10:43 against a 512MB limit, then the container
is OOMKilled at 10:44 (oom_killed_total=3, alert fired 10:44:30). go_heap_inuse_mb
tracks RSS, and GC-pressure warnings ("heap growing, forced GC did not reclaim")
appear just before the kill. This is a classic unbounded-growth memory leak with a
long, delayed onset -- not a spike.

## The culprit diff
Commit c6566fc ("record per-request candidate scores for offline tuning") was
deployed to recommendationservice at 08:25 -- ~2h19m before the OOMKill. Its diff
adds a package-level slice `var scoreLog []scoreRecord` and calls
`recordScores(...)` on every Score() request, appending a record (including the
full candidate slice) with no eviction, no cap, and no reset. That is the
unbounded per-request growth that produces the steady RSS climb. Tracing the climb
backward, it begins exactly at the 08:25 deploy of this commit.

## Why not the near-onset deploy (decoy)
f72cb9d ("prefetch trending items") is the *latest* recommendationservice deploy,
at 10:32 -- only ~12 minutes before the kill, which makes it the tempting "blame
the latest deploy" answer. But (1) its diff uses a fixed-size LRU
(trendingMax=256), so it is memory-bounded by construction, and (2) RSS was already
~473MB and had been climbing steadily for over two hours before 10:32, so the leak
predates this deploy and cannot be caused by it. Other surface-match decoys
(4bded17 preallocate JSON buffer, 966b58e sync.Pool reuse) touch buffers/memory but
are bounded. The reco_model_v3 flag flip at 10:15 is a distractor.

## Blast radius
frontend is downstream: its recommendation rail fails to render ("upstream
unavailable") once the reco pods start OOMKilling/restarting, and its
recommendation_render_error_ratio jumps from ~0.003 to ~0.27 at 10:44. frontend is
a victim, not the cause.

## Remediation
Roll back recommendationservice to the build before c6566fc.
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
