# Root-Cause Analysis

You are the on-call SRE for a platform built from independently deployed microservices.
A monitor just paged. Find the **single git commit** that caused this regression, identify the
**first service that started failing**, separate the **blast radius** (downstream services dragged
down by the cause) from the cause itself, and recommend a **remediation**.

The alert that fired is in `/workdir/data/alert.json`.

## The data in `/workdir/data/`

A frozen snapshot of the incident window. All timestamps are UTC and internally consistent.

| file | what it is |
|------|------------|
| `alert.json` | the monitor that fired (service, metric, threshold, `fired_at`) |
| `logs.ndjson` | one JSON log record per line (timestamp, service, severity_text, msg, trace_id, ...) |
| `metrics.csv` | `timestamp,service,metric,value` across a baseline + incident window |
| `traces.json` | OTel-style spans (service, name, start, duration_ms, status, parent_id) |
| `patterns.json` | clustered log signatures with `count`, `delta_vs_baseline`, `sentiment` |
| `context/commits.json` | every commit in the window: `sha`, `author`, `timestamp`, `message`, `files_changed[]`, and a `diff` (the actual code change) |
| `context/deploys.json` | deploy events: `timestamp`, `service`, `commit_sha`, `version` |
| `context/flags.json` | feature-flag changes near the window |

## Tools

`jq`, `grep`, `awk`, `sort`, `python3` and the usual shell utilities are installed. The data is
small — read it, slice it, correlate it.

## How to think about it

1. From the alert + metrics + traces, establish **what is actually broken** — the precise failure
   mechanism (the fault signature), and the **first** service that started failing.
2. Establish the **onset** time. Onset can be **delayed** well after the deploy that caused it
   (pools saturate, memory leaks grow, a path is only hit under later load).
3. Read the **`diff`** of the candidate commits and reason about which change could actually
   *produce this specific fault*. The commit messages are terse and will **not** name the bug —
   you must reason from the code change to the symptom, not from the message.
4. The culprit is **not** necessarily the most recent deploy, the commit on the loudest service,
   or the commit whose files look most related. The real cause may be in a **shared library or a
   dependency** of the failing service. Innocent changes are planted near onset to mislead you.
5. Distinguish **cause** from **blast radius**: a downstream service that times out waiting on the
   culprit is a victim, not the cause.
6. **The cause may not be a commit at all.** Many incidents are triggered operationally, with no
   guilty code change in the window — a traffic surge, an upstream provider/cloud outage, an
   expired TLS certificate, a node/infra problem, or bad input data. If **no** commit's diff
   actually produces the observed fault and the evidence points to an operational/external trigger,
   the correct answer is **`"none"`**. Do not convict an innocent commit just because one is there.

## Rules

- Do **NOT** speculate. Convict a commit **only if its diff actually produces the observed fault.**
- The latest deploy before onset is **not automatically** the culprit. Verify causality.
- If the evidence points to an operational/external cause (and no commit's diff explains the
  symptom), answer `root_cause_commit: "none"`. Guessing a commit when the cause is operational is
  a **wrong answer**, just like naming the wrong commit.
- Feature-flag changes in `flags.json` are **distractors**.

## Output (required)

Write your machine-checkable answer to **`/workdir/root_cause.json`**:

```json
{
  "root_cause_commit": "<full git sha from commits.json, OR \"none\" if no commit caused it>",
  "first_failing_service": "<service name>",
  "blast_radius": ["<downstream service>", "..."],
  "remediation": "<short action: e.g. rollback, roll-forward, config-revert, scale, failover, rotate-cert, feature-flag-disable>"
}
```

Also write a short free-form explanation to **`/workdir/reasoning.md`**: the timeline you
reconstructed, which diff is the cause and why (and why not the near-onset decoy), and the blast
radius. You are scored primarily on getting `root_cause_commit` exactly right.
