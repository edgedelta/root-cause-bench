# Root-Cause Analysis: recommendation-memory-leak

You are the on-call SRE for an e-commerce platform built from independently
deployed microservices. A monitor just paged. Your job is to find the **single
git commit** that caused this regression, identify the **first service that
started failing**, separate the **blast radius** (downstream services dragged
down by the cause) from the cause itself, and recommend a **remediation**.

## What happened

recommendationservice pods were OOMKilled ~12 minutes after a deploy; the storefront recommendation rail is failing to render.

The full alert is in `/workdir/data/alert.json`.

## The data in `/workdir/data/`

A frozen snapshot of the incident window. All timestamps are UTC and internally
consistent — the regression begins **after** the commit that caused it was
deployed.

| file | what it is |
|------|------------|
| `alert.json` | the monitor that fired (service, metric, threshold, `fired_at`) |
| `logs.ndjson` | one JSON log record per line (timestamp, service, severity_text, msg, trace_id, ...) |
| `metrics.csv` | `timestamp,service,metric,value` across a baseline + incident window |
| `traces.json` | OTel-style spans (service, name, start, duration_ms, status, parent_id) |
| `patterns.json` | clustered log signatures with `count`, `delta_vs_baseline`, `sentiment` |
| `context/commits.json` | every commit in the window: `sha`, `author`, `timestamp`, `message`, `files_changed[]` |
| `context/deploys.json` | deploy events: `timestamp`, `service`, `commit_sha`, `version` |
| `context/flags.json` | feature-flag changes near the window |

## Tools

`jq`, `grep`, `awk`, `sort`, `python3` and the usual shell utilities are
installed. The data is small — read it, slice it, correlate it. The platform's
query language is **CQL** (field equality like `severity_text:"ERROR"`, boolean
`AND`/`OR`/negation, numeric comparisons like `@duration_ms > 3000`; no regex,
no mid-string wildcards) — if you reason about queries, use CQL semantics, but
here you query the local files directly.

## How to think about it

1. Establish the **onset** time from the alert + metrics (when did the metric
   cross its threshold and what is the earliest service that degraded?).
2. Find the deploy(s) **before** onset. Remember onset can be **delayed** after
   the deploy that caused it (pools saturate, memory leaks, caches grow).
3. Map the deploy to its `commit_sha`, then read that commit's `message` and
   `files_changed[]` and check it plausibly explains the symptom.
4. RSS climbs gradually after the deploy; logs are mostly innocent until the kill. A plausible 'prefetch goroutine' commit deploys near onset but is not the leak.
5. Distinguish **cause** from **blast radius**: a downstream service that times
   out waiting on the culprit is a victim, not the cause.

## Rules

- Do **NOT** speculate. Pick the commit the evidence actually supports.
- The latest deploy before onset is **not automatically** the culprit — there
  are innocent deploys near onset planted to mislead you. Verify causality.
- Feature-flag changes in `flags.json` are **distractors** in this benchmark;
  the root cause is always a **git commit**.
- If genuinely uncertain between two commits, choose the one whose
  `files_changed[]` most directly touches the failing code path of the first
  failing service.

## Output (required)

Write your machine-checkable answer to **`/workdir/root_cause.json`**:

```json
{
  "root_cause_commit": "<full git sha from commits.json>",
  "first_failing_service": "<service name>",
  "blast_radius": ["<downstream service>", "..."],
  "remediation": "rollback" | "roll-forward" | "config-revert" | "scale" | "feature-flag-disable"
}
```

Also write a short free-form explanation to **`/workdir/reasoning.md`**: the
timeline you reconstructed, why this commit (and not the decoy near onset), and
what the blast radius was.

You are scored primarily on getting `root_cause_commit` exactly right.
