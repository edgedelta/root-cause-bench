# RootCauseBench

### Can AI find the commit that broke prod?

An open-source benchmark that drops a frontier LLM into a frozen production
incident — alert, logs, metrics, traces, patterns, and the full change context
(commits, deploys, feature flags) — and asks the only question that matters at
3am: **which commit caused this?**

No agent of ours. No EdgeDelta product in the loop. Every model gets the same
data and the same shell. We measure the reasoning, not the tooling.

---

## The question

A monitor pages. p99 latency is up 20×, or charges are 5xx-ing, or pods are
getting OOMKilled. Forty commits landed in the last three hours. Three services
deployed in the last two minutes. Someone flipped a feature flag. The on-call
engineer has to find the **one commit** that did it — and not get fooled by the
innocent CSS deploy that happened to land thirty seconds before the graph went
vertical.

That's the job. RootCauseBench asks whether an LLM can do it.

## What the benchmark measures

Given a frozen incident, the model must produce:

```json
{
  "root_cause_commit": "<sha>",
  "first_failing_service": "<service>",
  "blast_radius": ["<svc>", "..."],
  "remediation": "rollback" | "roll-forward" | "config-revert" | "scale" | "feature-flag-disable"
}
```

- **PRIMARY reward (the only thing that gates pass/fail):** does
  `root_cause_commit` exactly match the ground-truth culprit SHA?
- **Secondary signals (printed, never fail the run):** first-failing-service
  correctness, blast-radius Jaccard overlap vs truth, remediation match, and —
  the interesting one — **did the model fall for the innocent-deploy decoy?**
- **Graded reward (reporting only, never gates pass/fail):** `1.0` for the
  correct commit; `0.0` if the model blamed an innocent-deploy decoy (the
  cardinal failure — confidently wrong beats being unsure); otherwise partial
  credit capped at `0.5` from the secondary diagnosis (0.5 × first-failing-
  service + 0.3 × blast-radius Jaccard + 0.2 × remediation). The grader emits
  it per trial (`ROOTCAUSEBENCH_METRICS` stdout line + `verifier/metrics.json`)
  and the leaderboard ranks on **mean graded reward ± 95% CI**, which
  separates near-miss diagnoses from total whiffs and is robust to
  single-scenario flips.

Naming the right symptom is easy. Naming the right *commit* — separating cause
from blast radius, resisting "blame the latest deploy", and handling onset that
shows up minutes after the bad deploy — is the hard part.

## How it works

RootCauseBench is a set of **Terminal-Bench tasks** run by the
[Harbor](https://harborframework.com) harness with the default `terminus-2`
agent. We ship only **tasks + datasets + scoring**. The harness, the agent
loop, and the model are external and identical for every contender — this is a
deliberately thin, fully-open, *model-based* benchmark.

Each task spins up a Docker container, drops the frozen telemetry into
`/workdir/data/`, hands the model a shell with `jq`/`grep`/`python3`, and grades
the JSON it writes to `/workdir/root_cause.json`.

EdgeDelta's query language is **CQL** (field equality like
`severity_text:"ERROR"`, boolean `AND`/`OR`/negation, numeric comparisons like
`@duration_ms > 3000`; no regex, no mid-string wildcards). The scenarios are
written so a CQL-shaped mental model maps cleanly onto the local files.

## Task format

Standard Terminal-Bench. Each scenario under `datasets/rootcausebench/<name>/`:

```
task.toml            # metadata + timeouts
instruction.md       # the prompt the model sees
environment/
  Dockerfile         # python:3.12-slim + jq, COPYs data/ into /workdir/data/
  data/              # alert.json, logs.ndjson, metrics.csv, traces.json,
                     # patterns.json, context/{commits,deploys,flags}.json
solution/solve.sh    # oracle answer (validates the grader)
tests/
  test.sh            # installs uv + pytest, runs the grader, writes reward.txt
  test_outputs.py    # PRIMARY = exact culprit SHA; prints secondary metrics
  ground_truth.json  # injected only at verify time — the agent never sees it
```

See [`datasets/rootcausebench/README.md`](datasets/rootcausebench/README.md)
for the full data + ground-truth schema.

## Difficulty tiers

| tier | what makes it hard |
|------|--------------------|
| **easy** | one obvious culprit, clear failure signature (a panic stack trace), few distractors — but you still have to pick the *right* SHA. |
| **medium** | the culprit is buried among ~40 commits and an innocent deploy lands near onset as a decoy. |
| **hard** | **delayed onset** (the bad deploy detonates minutes later), multiple innocent deploys near onset, and a feature-flag flip in the same window. |

## Running it

Requires [Harbor](https://harborframework.com) (`uv tool install harbor`),
Docker, and an `OPENROUTER_API_KEY` (or provider keys) in `.env`.

Smoke test — one model, one scenario:

```bash
source .env && uv run harbor run -c configs/smoke-docker.yaml
```

Full run — all scenarios across several frontier models, 3 attempts each:

```bash
source .env && uv run harbor run -c configs/all-models-docker.yaml
```

Run a single scenario directly:

```bash
uv run harbor run \
  --path datasets \
  --task-name rootcausebench/inventory-connection-pool-exhaustion \
  --agent terminus-2 \
  --model openrouter/anthropic/claude-opus-4.6
```

Summarize results into a per-model / per-difficulty table:

```bash
uv run scripts/process_results.py jobs/<timestamp>
```

## Leaderboard

Frozen run (v2): **24 scenarios x 20 models x 3 attempts = 1440 trials**, Harbor `terminus-2` over OpenRouter, 2026-07-07/10, all agents at an 1800s timeout. Models are ranked on **mean graded reward** (1.0 correct culprit; 0.0 for blaming a decoy; partial credit ≤ 0.5 otherwise; ± 95% CI over the 72 trials), with binary pass rates alongside. The three trials that hit `AgentTimeoutError` were re-run per methodology (timeouts are infra errors, not model failures). Full per-trial results (outcome, graded reward, cost, tokens, timing per model) + rollups are committed under [`benchmark-results/`](benchmark-results/).

> v1 → v2: the original 2026-06-30/07-02 run used a 600s agent timeout, which cost
> deepseek-v4-flash 4 trials and four other models 1 each as `AgentTimeoutError`. v2
> raises the timeout to 1800s for every model, treats residual timeouts as retries,
> captures per-trial graded rewards, and adds sakana/fugu-ultra and
> anthropic/claude-fable-5. Notable moves vs v1: claude-opus-4.8 93% → 99%,
> claude-haiku-4.5 35% → 47%, gemini-3.1-flash-lite 56% → 60% (v1's tail numbers were
> noisier than its top).

| Model | Mean graded reward (95% CI) | Pass rate | easy | medium | hard | no-code-cause |
|---|---|---|---|---|---|---|
| glm-5.2 | **1.000 ± 0.000** | 100% | 100% | 100% | 100% | 100% |
| grok-4.5 | **1.000 ± 0.000** | 100% | 100% | 100% | 100% | 100% |
| claude-opus-4.8 | **0.986 ± 0.027** | 99% | 100% | 100% | 97% | 100% |
| claude-fable-5 | **0.979 ± 0.030** | 97% | 100% | 100% | 94% | 100% |
| gpt-5.4 | **0.972 ± 0.038** | 97% | 100% | 100% | 94% | 100% |
| fugu-ultra | **0.972 ± 0.038** | 97% | 100% | 100% | 94% | 95% |
| deepseek-v4-flash | **0.964 ± 0.041** | 96% | 100% | 96% | 94% | 90% |
| gpt-5.5 | **0.958 ± 0.046** | 96% | 100% | 100% | 92% | 90% |
| gemini-3.5-flash | **0.958 ± 0.046** | 96% | 100% | 100% | 92% | 86% |
| gemini-3.1-pro-preview | **0.958 ± 0.046** | 96% | 100% | 100% | 92% | 86% |
| claude-sonnet-4.6 | **0.958 ± 0.046** | 96% | 100% | 100% | 92% | 86% |
| kimi-k2.5 | **0.875 ± 0.077** | 88% | 100% | 96% | 78% | 67% |
| kimi-k2-thinking | **0.875 ± 0.074** | 86% | 100% | 89% | 81% | 67% |
| gpt-5.4-mini | **0.851 ± 0.076** | 82% | 78% | 89% | 78% | 90% |
| qwen3-235b-a22b-2507 | **0.767 ± 0.096** | 75% | 89% | 74% | 72% | 86% |
| gemini-3.1-flash-lite | **0.607 ± 0.112** | 60% | 100% | 59% | 50% | 29% |
| gpt-oss-120b | **0.534 ± 0.111** | 50% | 100% | 56% | 33% | 38% |
| claude-haiku-4.5 | **0.507 ± 0.111** | 47% | 78% | 41% | 44% | 33% |
| qwen3-32b | **0.450 ± 0.111** | 42% | 33% | 52% | 36% | 38% |
| gpt-oss-20b | **0.386 ± 0.097** | 29% | 56% | 30% | 22% | 52% |

## Baselines: can a script find the culprit?

A benchmark whose culprit falls to a trivial policy measures nothing. Five deterministic,
non-LLM baselines answer every scenario using only the data the agent sees and are scored
with the grader's primary rule ([`scripts/run_baselines.py`](scripts/run_baselines.py);
per-scenario results in
[`benchmark-results/rootcausebench/baselines.json`](benchmark-results/rootcausebench/baselines.json)):

| Baseline | Policy | Pass rate | Decoy hits | easy | medium | hard |
|---|---|---|---|---|---|---|
| `latest-commit` | blame the newest commit | 0/24 | 0 | 0/3 | 0/9 | 0/12 |
| `always-none` | answer "none" every time | 7/24 | 0 | 0/3 | 3/9 | 4/12 |
| `latest-deploy` | blame the last deploy before onset | 1/24 | **22** | 1/3 | 0/9 | 0/12 |
| `alert-service-deploy` | last pre-onset deploy to the alerting service | 5/24 | 18 | 2/3 | 0/9 | 3/12 |
| `scripted-rca` | ~20-line heuristic: service match + alert keywords in the diff, most recent wins | 7/24 | 17 | 3/3 | 0/9 | 4/12 |

Three takeaways:

- **The decoy design works.** The classic 3am heuristic — *blame the last deploy before
  onset* — goes 1/24 and lands on an innocent-deploy decoy in **22 of 24 scenarios**.
  Every decoy is placed exactly where that reflex looks.
- **"none" is a prior, not an answer.** `always-none` collects the 7 no-code-cause
  scenarios (29% pass) while scoring zero on every real culprit — the same trap a model
  falls into if it treats "no code cause" as a safe default.
- **Known soft spots.** `scripted-rca` (match the alerting service, grep the diffs for
  alert keywords) solves all 3 easy scenarios and 4 hard ones — those culprits are
  findable without understanding the diff. CI warns on each; they are slated for
  hardening in a future data revision, and the inverted easy/hard split there is a
  tier-calibration signal.

CI ([`oracle-check`](.github/workflows/oracle-check.yml)) enforces on every push: every
scenario's oracle (`solution/solve.sh`) satisfies its grader and matches ground truth on
every field, all culprit/decoy/deploy SHAs resolve against `commits.json`, and
`latest-commit` never names a culprit (that would make a scenario trivially gameable).

## Scenarios

Twenty-four frozen incidents, three kinds:

- **Real-culprit (17)** — a single commit caused the regression and the model must
  name its SHA by reading the **diff** (commit messages are neutralized and never
  describe the fault). Misleading structures throughout: cross-service / shared-
  library culprits (the failing service didn't change), better-surface-match
  decoys on the loud service, and delayed-onset faults where an innocent deploy
  lands right at onset. A few are fault injections on a synthetic microservices
  app (Online Boutique fork); the rest are reconstructions of production incident
  classes.
- **No-code-cause (7)** — there is **no guilty commit**; the trigger is
  operational/external (upstream provider outage, cloud-region impairment, DNS
  degradation, traffic surge, noisy-neighbor node, expired TLS cert, poison data
  record), with innocent commits planted as bait. The correct answer is `"none"`.
  These measure whether a model will *abstain* instead of confabulating a culprit.
- The reconstructions **use a fictional platform's service names** (`olapdb-tso`, `ai-agent-svc`,
  `ai-memory-svc`, `metric-ingestor-1`, `kafka-metric-ingestor`,
  `pipeline-transformer`, `workflow-engine`, `dashboard-svc`, `platform-api`, the
  `stream-taskmanager` Flink taskmanager, …) and realistic log signatures
  (FoundationDB/CnchLock transaction timeouts, DynamoDB
  `ProvisionedThroughputExceededException`, missing-relation errors,
  protobuf-runtime startup panics). All service, host, and commit identifiers are
  fictional stand-ins; the scenarios reproduce common incident *classes*, not any
  specific real incident. See
  use a fictional platform's service names (`olapdb-tso`, `ai-agent-svc`,
  `ai-memory-svc`, `metric-ingestor-1`, `kafka-metric-ingestor`,
  `pipeline-transformer`, `workflow-engine`, `dashboard-svc`, `platform-api`, the
  `stream-taskmanager` Flink taskmanager, …) and realistic log signatures
  (FoundationDB/CnchLock transaction timeouts, DynamoDB
  `ProvisionedThroughputExceededException`, missing-relation errors,
  protobuf-runtime startup panics). All service, host, and commit identifiers are
  fictional stand-ins; the scenarios reproduce common incident *classes*, not any
  specific real incident. See
  [`datasets/rootcausebench/README.md`](datasets/rootcausebench/README.md) for
  the full scenario index.

## How scenarios are generated

Scenarios are **fault injections on a real microservices application** (a fork
of GCP's microservices-demo / "Online Boutique"), or reconstructions of
representative production incident classes on a fictional platform. The methodology:

1. Run the app under steady synthetic load (storefront + cart + checkout RPS).
2. Author a single commit that introduces a real regression class — N+1 query,
   nil deref, connection-pool exhaustion, memory leak — in one service, and
   surround it with dozens of innocent commits (dep bumps, refactors, docs)
   across the same window.
3. Deploy the culprit. Near the same time, deploy one or more *innocent*
   changes and flip a feature flag — these become the decoys.
4. Capture the telemetry window (logs, metrics, traces, clustered patterns) plus
   the change context, and freeze it to small, internally time-consistent
   fixtures (**onset strictly after the culprit deploy**; delayed onset for
   pool/leak faults).
5. Emit `ground_truth.json` (culprit SHA, first failing service, blast radius,
   remediation, decoy SHAs).

`tools/generate_scenario.py` documents this pipeline and includes a functional
synthetic generator that scaffolds a new scenario skeleton with injectable
distractor commits.

## Building your own scenarios

```bash
uv run tools/generate_scenario.py \
  --name my-new-fault \
  --service paymentservice \
  --difficulty medium \
  --culprit-message "feat(payment): introduce the bug" \
  --culprit-files services/payment/charge.go \
  --blast checkoutservice frontend \
  --distractors 30
```

This writes a full scenario skeleton (all six task files + telemetry). Hand-edit
the telemetry to add your real failure signature, then validate that the oracle
answer passes:

```bash
bash datasets/rootcausebench/my-new-fault/solution/solve.sh   # writes the oracle answer
# point test_outputs.py at it and confirm it passes
```

## Why we built this

Root-cause analysis is the slowest, most expensive part of an incident, and it's
exactly the kind of cross-signal reasoning people hope LLMs can shoulder. We
build observability tooling at [Edge Delta](https://edgedelta.com), so we care a
lot about whether models can actually do this — and about being honest when they
can't. RootCauseBench is neutral by design: no product, no agent of ours, just
the question and the data.

## License

[Apache-2.0](LICENSE) © Edge Delta, Inc.
