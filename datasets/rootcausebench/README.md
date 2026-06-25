# RootCauseBench dataset

Each subdirectory is one **frozen incident**. The agent gets a snapshot of
telemetry plus change context and must name the single git commit that caused
the regression.

## Scenario layout

```
<scenario>/
├── task.toml                 # Terminal-Bench task metadata
├── instruction.md            # the prompt the model sees
├── environment/
│   ├── Dockerfile            # python:3.12-slim + jq; COPYs data/ to /workdir/data/
│   └── data/                 # the frozen incident (visible to the agent)
│       ├── alert.json
│       ├── logs.ndjson
│       ├── metrics.csv
│       ├── traces.json
│       ├── patterns.json
│       └── context/
│           ├── commits.json
│           ├── deploys.json
│           └── flags.json
├── solution/
│   └── solve.sh              # oracle: writes the correct /workdir/root_cause.json
└── tests/
    ├── test.sh               # installs uv+pytest, runs the grader
    ├── test_outputs.py       # grader (PRIMARY = exact culprit SHA)
    └── ground_truth.json     # injected ONLY at verify time — agent never sees it
```

## Data schema (what the agent reads from `/workdir/data/`)

**alert.json** — the page that fired:
```json
{ "service": "checkoutservice", "metric": "http_server_duration_p99_ms",
  "threshold": 800, "observed": 4120, "fired_at": "2026-06-18T15:06:00Z",
  "severity": "critical", "monitor": "checkout-p99-latency", "summary": "..." }
```

**logs.ndjson** — one JSON record per line:
```json
{ "timestamp": "...", "service": "...", "severity_text": "ERROR",
  "msg": "...", "trace_id": "...", "http.route": "...", ... }
```

**metrics.csv** — long format, baseline + incident window:
```
timestamp,service,metric,value
2026-06-18T14:00:00Z,checkoutservice,http_server_duration_p99_ms,212.4
```

**traces.json** — list of OTel-style spans:
```json
{ "trace_id": "...", "span_id": "...", "parent_id": "...", "service": "...",
  "name": "...", "start": "...", "duration_ms": 4090, "status": "OK" }
```

**patterns.json** — clustered log signatures:
```json
{ "signature": "slow request: PlaceOrder exceeded <N>ms", "service": "...",
  "count": 412, "delta_vs_baseline": "+412", "sentiment": "negative" }
```

**context/commits.json** — every commit in the window (the culprit + many
distractors): `sha`, `author`, `timestamp`, `message`, `files_changed[]`.

**context/deploys.json** — deploy events: `timestamp`, `service`,
`commit_sha`, `version`. At least one **innocent deploy lands near onset** as a
decoy.

**context/flags.json** — feature-flag changes near the window. In v1 these are
**always distractors**; the root cause is a git commit.

### Time consistency

Every scenario is internally consistent: the incident **onset is strictly after
the culprit deploy**. Onset may be *delayed* (connection-pool saturation,
memory-leak OOMKill). Innocent deploys and flag flips are placed near onset to
punish "blame the latest change" heuristics.

## Ground truth (`tests/ground_truth.json`)

```json
{
  "scenario": "checkout-latency-n-plus-one",
  "root_cause_commit": "<full 40-char sha>",
  "first_failing_service": "checkoutservice",
  "blast_radius": ["cartservice", "frontend"],
  "remediation": "rollback",
  "decoy_deploy_commits": ["<sha of the innocent deploy>"],
  "notes": "human explanation used in failure messages"
}
```

## Grading

- **PRIMARY (binary reward):** the model's `root_cause_commit` must exactly
  match `root_cause_commit` (a correct ≥7-char short SHA prefix is accepted).
- **SECONDARY (printed, never fatal):** whether `first_failing_service` is
  correct, the Jaccard overlap of `blast_radius` vs truth, whether the
  remediation matches, and **whether the model fell for the innocent-deploy
  decoy** (picked a SHA in `decoy_deploy_commits`).

## Scenarios

The first four scenarios are fault injections on a synthetic microservices app
(see "How scenarios are generated" in the top-level README). The remaining six
are **reconstructions of representative production incident classes** on a
fictional platform — they use fictional service names (`olapdb-tso`,
`ai-agent-svc`, `ai-memory-svc`, `metric-ingestor-1`, `kafka-metric-ingestor`,
`pipeline-transformer`, `workflow-engine`, `dashboard-svc`, `platform-api`, the
`stream-taskmanager` Flink taskmanager, …), realistic log signatures
(FoundationDB/CnchLock/TransactionCoordinator, DynamoDB
`ProvisionedThroughputExceededException`, sqlalchemy missing-relation,
protobuf-runtime panics), and common incident classes. All service, host, and
commit identifiers are fictional stand-ins; the scenarios do not mirror any
specific real incident.

| scenario | difficulty | fault | onset | decoys |
|----------|------------|-------|-------|--------|
| `payment-nil-deref-panic` | easy | nil-pointer deref in payment, panic on every charge | immediate | none |
| `checkout-latency-n-plus-one` | medium | per-item catalog lookup → N+1 queries, p99 blows up | immediate | innocent frontend CSS deploy ~30s before onset |
| `inventory-connection-pool-exhaustion` | hard | code lowers DB max-conns 50→10; pool saturates | ~8 min delayed | 2 innocent deploys + 1 feature-flag flip near onset |
| `recommendation-memory-leak` | hard | unbounded package-level cache → OOMKill | ~12 min delayed | innocent "prefetch goroutine" deploy near onset |
| `olapdb-tso-cas-retry-budget` *(real)* | hard | `#olapdb Lower TSO CAS retry budget` → FoundationDB txn timeouts in TSO leader-election → `olapdb-tso` fails, `stream-taskmanager` Flink job unhealthy | ~6 min delayed | innocent `dashboard-svc` deploy + feature-flag flip near onset |
| `ai-agent-registration-missing` *(real)* | medium | `#ai Refactor agent bootstrap` drops predefined-agent registration → `ai-agent-svc` 500s on agent lookups | immediate (first request after restart) | innocent `web` restyle deploy near onset |
| `dynamodb-write-capacity-breach` *(real)* | hard | `#ai Remove write batching in memory store` → DynamoDB write-capacity throttling builds → `ai-memory-svc` write failures | ~8 min delayed | 2 innocent deploys + 1 feature-flag flip near onset |
| `metric-ingestor-metadata-deser` *(real)* | medium | `#ingest Rename metadata field on metric envelope` breaks deserialization → `metric-ingestor-1` fails, `metric-ingestor-1-iq` backs up | ~2 min | innocent aws-sdk bump deployed to `kafka-metric-ingestor` near onset |
| `dashboard-db-schema-missing-table` *(real)* | easy | `#dashboard Add dashboards table migration` ships code referencing a table whose migration was omitted → missing-table 500s | immediate | innocent `dashboard-svc` theme deploy near onset |
| `transformer-dependency-startup-crash` *(real)* | medium | `#transformer Bump protobuf runtime` → runtime version conflict → `pipeline-transformer` CrashLoopBackOff | immediate (startup) | innocent `#deps Bump aws-sdk minor` deployed to `workflow-engine` near onset — punishes "blame the dep bump" |
