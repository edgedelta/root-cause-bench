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

Some scenarios are fault injections on a synthetic microservices app (see "How
scenarios are generated" in the top-level README); most are
**reconstructions of representative production incident classes** on a
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
| `ai-agent-registration-missing` *(real)* | medium | `#ai Refactor agent bootstrap` diff DELETES the `registerPredefinedAgents()` call → `ai-agent-svc` 500s on agent lookups | immediate (first request after restart) | a sibling `#ai Adjust predefined-agent lookup handler` ships in the SAME release and edits the exact failing endpoint (better surface match) + innocent `web` restyle deploy near onset |
| `dynamodb-write-capacity-breach` *(real)* | hard | `#ai Remove write batching in memory store` → DynamoDB write-capacity throttling builds → `ai-memory-svc` write failures | ~8 min delayed | 2 innocent deploys + 1 feature-flag flip near onset |
| `metric-ingestor-metadata-deser` *(real)* | medium | `#ingest Rename metadata field on metric envelope` breaks deserialization → `metric-ingestor-1` fails, `metric-ingestor-1-iq` backs up | ~2 min | innocent aws-sdk bump deployed to `kafka-metric-ingestor` near onset |
| `dashboard-db-schema-missing-table` *(real)* | easy | `#dashboard Add dashboards table migration` ships code referencing a table whose migration was omitted → missing-table 500s | immediate | innocent `dashboard-svc` theme deploy near onset |
| `transformer-dependency-startup-crash` *(real)* | medium | `#transformer Bump protobuf runtime` → runtime version conflict → `pipeline-transformer` CrashLoopBackOff | immediate (startup) | innocent `#deps Bump aws-sdk minor` deployed to `workflow-engine` near onset — punishes "blame the dep bump" |
| `shared-config-pool-drain` *(adversarial / guilty-decoy)* | adversarial | shared-library `pkg/dbpool/config.go` refactor swaps a 30s acquire-timeout duration for an int-milliseconds knob defaulting to 3000 — silently shrinks 30s → 3s; ships via a `paymentservice` deploy (not the alerting service) | ~15 min delayed | guilty-looking `checkoutservice` retry-loop commit deployed at visible onset (exonerated: `db_conn_wait_ms` climbs before its deploy, and its feature flag is off throughout) + innocent frontend CSS deploy near onset |
| `catalog-cache-key-cardinality` *(adversarial / beyond-context)* | adversarial | monorepo, 303 commits, ~12MB telemetry — `pkg/cache/key.go` refactor adds `req.SessionID` to the catalog cache key, exploding key cardinality; `cache_hit_ratio` decays toward 0.31 and `redis_mem_mb` ramps over ~30h before `catalog_latency_p99_ms` finally breaches threshold | ~30h delayed | guilty-looking `perf(catalog): tune redis client timeouts` deploy on the alerting service 25 min before the alert (exonerated: hit-ratio decay predates it by ~29h) + innocent `dashboard-svc` deploy near onset |
| `notification-buffer-oom-silent` *(adversarial / degraded-telemetry)* | adversarial | `services/notification/dispatch.go` swaps a bounded drop-on-full channel for an unbounded batch slice; under a webhook-consumer backlog `container_memory_rss_mb` and `dispatch_queue_depth` ramp from the 08:40 deploy to a 4GB OOMKill at 09:40 (`container_restarts` steps 0→7) — `notification-svc`'s own logs go silent from onset onward (`drop_logs` degradation), so the failing service must be inferred from peers' `connection refused` errors and the metric ramp/flatline, not from its own telemetry | immediate OOM at onset (60 min after culprit deploy) | loud downstream `fix(workflow): improve dispatch error logging` deploy on the alerting service 6 min before the alert (exonerated: the connection-refused spam predates its deploy by 12 min, and the diff only touches a log message) |
| `payment-refund-poison-batch` *(adversarial / abstention, no-code-cause)* | adversarial | a partner refund batch delivers a malformed record (`rfnd_8842107763`, currency `"XBT"`) at 11:02; `payment-refund-svc`'s validator correctly rejects it and, with no DLQ, redelivers the same record forever — `refund_processed_per_min` steps to 0, `refund_backlog_depth` ramps to 5200; `billing-api` (victim) times out polling status and alerts at 11:34 | immediate (no delay; the culprit is data, not a commit) | guilty-looking `perf(refunds): faster amount parsing` deployed to `payment-refund-svc` 7 min pre-onset (exonerated: touches only `parse.go`, never the untouched `validate.go` that raises the currency error, and refunds settle normally for the full 7 min between that deploy and onset) + innocent partner-sdk `go.mod` bump near the alert — correct answer is `root_cause_commit: "none"` |
| `orders-index-migration-drift` *(adversarial / guilty-decoy)* | adversarial | a `chore(db): consolidate orders table indexes` migration drops `idx_orders_tenant_created` and adds a non-covering `(status, created_at)` composite; `db_rows_examined` ramps from the migration deploy while `orders_latency_p99_ms` only breaches threshold ~40h later as table growth compounds the scan cost | ~40h delayed | two guilty-looking `orders-api` deploys in the hours before the alert (exonerated by semantics, not timing): a query-builder refactor whose `ToSql()` renders byte-identical SQL to the raw string it replaced, and a `defer rows.Close()` fix that only releases a resource — the wrong direction for a scan-cost regression — plus innocent frontend CSS and `go.mod` version-bump deploys near onset/alert |
| `webhook-keepalive-default-flip` *(adversarial / guilty-decoy)* | adversarial | `chore(webhooks): bump httpkit 1.8.4 -> 2.0.0` on `webhook-dispatcher` swaps `httpkit.New()` for `httpkit.NewClient(httpkit.Config{})`; the zero-value `Config{}` silently disables keep-alive, so every webhook POST opens a fresh TCP+TLS handshake until ephemeral ports exhaust (`tcp_new_conns_per_s` 12→480, connect errors) | ~15 min delayed | pre-onset `sync.Pool` buffer-pooling deploy on the same service (exonerated: `container_memory_rss_mb` stays flat — memory-shaped, connection-irrelevant) + a post-onset error-wrapping refactor on the exact failing function (exonerated: only appends endpoint context to an already-wrapped error, and deploys after the connect failures had already started) + innocent `billing-api` PDF-margin deploy near the alert and an unrelated background-service `go.mod` bump |
| `orders-fanout-nplusone` *(adversarial / beyond-context)* | adversarial | monorepo, 286 commits, ~25MB telemetry — `refactor(orders): simplify item hydration` (`services/orders-api/items.go`) replaces a batched `WHERE order_id IN (...)` load with a per-item `GetItem` loop; `db_queries_per_request` ramps 3→~85 over 28h from the deploy while `orders_latency_p99_ms` only breaches threshold near the alert; a hand-authored exemplar trace shows a dozen sequential `db.query order_items` child spans fanning out under one `ListOrders` span — the N+1 made directly visible | ~30h delayed | flag-gated `feat(orders): cache order summaries` deployed 6h pre-alert (exonerated: `orders_summary_cache` shown created-OFF in flags.json, never flipped) + a `CREATE INDEX` migration on `order_items(order_id)` deployed 3h pre-alert (exonerated: an index addition is the wrong direction — it can only speed the very queries at issue) + an unrelated DB-pool-size bump and an innocent dashboard-widget deploy near the alert |
| `ingest-partition-skew` *(adversarial / beyond-context)* | adversarial | monorepo, 267 commits, ~27MB telemetry — `refactor(ingest): stable partitioning for tenant affinity` (`services/event-producer/partition.go`) swaps the Kafka partition key from `hash(msg.DeviceID)` to `hash(msg.TenantID)`, concentrating a whale tenant onto one partition; `kafka-metric-ingestor` exposes 8 per-partition lag gauges — partitions 0-6 stay flat while `consumer_lag_partition_7` alone ramps 300→~900,000 starting 1h after the deploy — while `dashboard-svc`'s `chart_data_staleness_s` only breaches threshold ~18h later as the backlog starves chart refreshes | ~18h delayed | a Kafka-client version bump renaming `RangeAssignor`→`RangeAssignorName` (exonerated: semantics-preserving rename, same assignor) + two throughput-*raising* consumer tuning deploys (`max.poll.records` 500→1000, `fetch.max.bytes` 1MB→5MB; exonerated: both apply uniformly across all partitions and can't explain a single-partition-7 divergence, plus deploy well after the lag ramp began) + an unrelated producer `batch.size` bump and an innocent dashboard-widget deploy near the alert |
| `report-scheduler-lock-removal` *(adversarial / beyond-context)* | adversarial | monorepo, 259 commits, ~25MB telemetry — `refactor(scheduler): simplify job runner` (`services/report-scheduler/runner.go`) deletes the `s.locks.Acquire`/`ErrHeld`/`defer lock.Release()` guard around report generation, so a 30-minute cron tick that used to block behind a slow-running job now stacks a new overlapping job instead; `concurrent_report_jobs` ramps 1→14 in a shape that lines up, tick-for-tick, with the cron cadence visible in `report job started` log lines, while `report_db_cpu_pct` climbs hours before `dashboard-svc`'s `report_freshness_s` finally breaches threshold ~26h after the deploy | ~26h delayed | a flag-gated `feat(scheduler): enable parallel report generation workers` deploy that reads as the most plausible culprit in the scenario (exonerated: `scheduler_parallel_workers` shown created OFF in flags.json, never flipped) + a db-pool-size *increase* (15→25; exonerated: wrong direction, and `report_db_active_connections` was already saturating the old 15-cap before this deploy, proving organic growth) + a generator page-size bump (exonerated: a dedicated per-job `report_job_duration_s` metric stays flat through and after this deploy, only rising later as concurrency climbs) + an innocent dashboard-widget deploy near the alert |
| `session-cache-clockskew` *(adversarial / degraded-telemetry)* | adversarial | `perf(session-cache): approximate LFU eviction` (`services/session-cache/eviction.go`) replaces LRU with a sampled-LFU evictor (sample size 3) whose `Set()` unconditionally resets `freq[key]=1` on every write and whose `Get()` never increments it — every key's frequency is permanently 1, so eviction degenerates to uniform-random and pathologically thrashes hot keys under Zipfian session access; `cache_hit_ratio` decays 0.96→0.55 and `auth-gw`'s downstream `session_lookup_p95_ms` ramps 10 min later — first `clock_skew` scenario: `auth-gw`'s LOGS ONLY are shifted +90s (its metrics and every trace span stay true), detected via a deterministic 1/min heartbeat log landing on `:30` instead of `:00` seconds and a 90s gap between `auth-gw`'s own WARN logs and its own unskewed metric ramp | 10 min delayed | the skew manufactures a decoy causal story: `auth-gw`'s skewed logs make its own innocent `feat(auth): structured session claims logging` deploy (true timestamp already 1 min post-onset) *appear* to precede a 10.5-min-later error onset — mirroring the real culprit's true 10-min deploy-to-onset gap, for the wrong service (exonerated: logging-only diff, and deploys.json timestamps are never skewed) + a pre-onset session-TTL *raise* (wrong direction) + a semantics-preserving `sync.RWMutex` swap + an auth-gw connection-pool *raise* deployed mid-ramp (wrong direction) + an innocent frontend banner-copy deploy near the alert |
| `config-fanout-sampled-traces` *(adversarial / degraded-telemetry)* | adversarial | `refactor(pipeline): per-record config resolution` (`services/pipeline-transformer/transform.go`) moves a cached `s.config.Get(ctx, batch[0].Type)` lookup from once-per-batch to once-per-record inside the loop; `config_svc_requests_per_s` ramps 40→3900 (≈ batches/s × 96 records/batch, derivable from a constant `records=96` field on the routine `batch flushed` log) while `pipeline-transformer`'s own `batch_process_p95_ms` ramps in lockstep and `config-svc`'s `rpc_latency_p95_ms` degrades 7 min later as the victim of the fanout — first `sample_traces` scenario: whole traces are kept/dropped at 1% via `md5(trace_id) % 10000 < 100`, decimating nearly all background trace traffic; two hand-authored exemplars were chosen with trace_ids verified to survive sampling, and the surviving post-onset trace deliberately shows only 3 generic `config.Get` child spans at normal durations (not the full ~96×) so the real magnitude must come from the metric, not the trace | 10 min delayed | pre-onset `perf(config-svc): add response compression` (exonerated: reshapes response bytes, can't multiply request count) + a `pipeline_parallel_batches`-flag-gated parallel-workers deploy shown created OFF in flags.json + a same-service, 5-minutes-later semantics-preserving metrics-helper extraction on `pipeline-transformer` (right file family, zero control-flow change) + an innocent dashboard banner-copy deploy near the alert |
| `ingester-flush-interval-oom` *(adversarial / degraded-telemetry)* | adversarial | comment-free `perf(metric-ingester): adaptive flush scheduling` (`services/metric-ingester/flush.go`) replaces a fixed `flushEvery := 30 * time.Second` with `time.Duration(max(30, len(b.pending)/b.ratePerMin)) * time.Second` — dividing a raw point count by a per-MINUTE rate and feeding the quotient straight into a `* time.Second` duration, so under sustained load the interval balloons to ~300s (10x baseline) in a runaway feedback loop; `buffered_points` ramps 40k→2.4M and `container_memory_rss_mb` ramps 420→4090MB from 08:45 to a 10:20 OOM (`container_restarts` steps 0→5), with `points_flushed_per_min` collapsing 780→95 in lockstep — no `flush_interval_s` gauge is ever exposed, so the mechanism must be read from the diff and inferred from downstream metrics, not quoted from telemetry | ~1h55m delayed | first "misleading patterns" scenario: patterns.json is headlined by a stale `[[patterns_extra]]` entry ("gc pause exceeded budget" on `query-svc`, count 900, delta +3 — pre-existing chatter) sitting ABOVE both real incident patterns (query-svc upstream-timeout ERROR at 560, platform-api query-failure ERROR at 200), baiting a solver who trusts pattern-count ranking alone; meanwhile metric-ingester's own flush-degradation WARN log is marked `in_patterns = false` so the clusterer "misses" it even though the rows sit in logs.ndjson verbatim + pre-onset `perf(metric-ingester): zstd compression level 3->8` (exonerated: `cpu_pct` stays flat at baseline throughout, so a CPU-shaped read is contradicted by the data) + a semantics-preserving `chore(metric-ingester): bump protobuf runtime` (go.mod bump + regenerated stub header only) + innocent log-field-rename and metric-label-rename deploys at classic near-onset/near-alert bait positions |
