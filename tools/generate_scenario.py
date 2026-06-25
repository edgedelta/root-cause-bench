#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""generate_scenario.py — scaffold a new RootCauseBench scenario.

## The real pipeline (how the shipped scenarios were made)

RootCauseBench scenarios are *fault-injection* incidents on a real
microservices application (we use a fork of GCP's microservices-demo /
"Online Boutique" — frontend, cartservice, checkoutservice, paymentservice,
productcatalogservice, recommendationservice, shippingservice, ...). The
methodology:

  1. Stand the app up under synthetic load (a load generator hitting the
     storefront, cart, and checkout flows at a steady RPS).
  2. Pick a real regression class (N+1 query, nil deref, connection-pool
     exhaustion, memory leak) and write a single commit that introduces it in
     one service. Surround it with dozens of innocent commits (dependency
     bumps, refactors, docs) authored across the same window.
  3. Deploy the culprit commit. Around the same time, deploy one or more
     *innocent* changes (a CSS restyle, a tax-rounding fix) and flip a feature
     flag — these become decoys that punish "blame the latest/biggest change".
  4. Record the telemetry window: logs, metrics, traces, clustered patterns,
     plus the change context (commits / deploys / flags). Freeze it to small,
     internally time-consistent fixtures (onset strictly AFTER the culprit
     deploy; delayed onset for pool/leak faults).
  5. Emit ground_truth.json (the culprit SHA, first failing service, blast
     radius, remediation, and the decoy commit SHAs) into tests/.

The shipped scenarios were produced by that pipeline and then hand-tuned for
realism. This script provides a *functional synthetic generator* so you can
scaffold a new scenario skeleton (with injectable distractor commits) without
re-running the whole app-under-load harness. Hand-edit the telemetry afterward
to add the failure signature you care about.

## Usage

    uv run tools/generate_scenario.py \
        --name my-new-fault \
        --service paymentservice \
        --difficulty medium \
        --culprit-message "feat(payment): introduce the bug" \
        --culprit-files services/payment/charge.go \
        --blast checkoutservice frontend \
        --distractors 30

Writes a new dir under datasets/rootcausebench/<name>/ with task.toml,
instruction.md, environment/Dockerfile, environment/data/*, solution/solve.sh,
tests/test.sh, tests/test_outputs.py and tests/ground_truth.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import shutil

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASETS = os.path.join(REPO_ROOT, "datasets", "rootcausebench")
TEMPLATE = os.path.join(DATASETS, "payment-nil-deref-panic")  # copy shared test wiring from here

INNOCENT = [
    ("chore: bump go.mod dependencies", ["go.mod", "go.sum"]),
    ("docs: update API reference", ["docs/api/orders.md"]),
    ("test: add table-driven tests", ["pkg/money/convert_test.go"]),
    ("refactor: extract response writer helper", ["internal/httputil/writer.go"]),
    ("ci: cache go build", [".github/workflows/build.yml"]),
    ("feat: structured logging fields", ["internal/middleware/log.go"]),
    ("fix: correct typo in error message", ["internal/errors/messages.go"]),
    ("perf: preallocate buffer in JSON encoder", ["pkg/codec/json.go"]),
    ("feat: add /readyz endpoint", ["internal/health/ready.go"]),
    ("refactor: simplify config loading", ["internal/config/load.go"]),
]


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(40))


def main() -> None:
    ap = argparse.ArgumentParser(description="Scaffold a RootCauseBench scenario")
    ap.add_argument("--name", required=True)
    ap.add_argument("--service", required=True, help="first failing service")
    ap.add_argument("--difficulty", default="medium", choices=["easy", "medium", "hard"])
    ap.add_argument("--culprit-message", required=True)
    ap.add_argument("--culprit-files", nargs="+", required=True)
    ap.add_argument("--blast", nargs="*", default=[], help="downstream blast-radius services")
    ap.add_argument("--distractors", type=int, default=20)
    ap.add_argument("--remediation", default="rollback",
                    choices=["rollback", "roll-forward", "config-revert", "scale", "feature-flag-disable"])
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rng = random.Random(args.seed or hash(args.name) & 0xFFFF)
    sdir = os.path.join(DATASETS, args.name)
    data = os.path.join(sdir, "environment", "data")
    os.makedirs(os.path.join(data, "context"), exist_ok=True)
    os.makedirs(os.path.join(sdir, "solution"), exist_ok=True)
    os.makedirs(os.path.join(sdir, "tests"), exist_ok=True)
    os.makedirs(os.path.join(sdir, "environment"), exist_ok=True)

    base = dt.datetime(2026, 1, 1, 12, 0, 0)
    culprit_ts = base + dt.timedelta(minutes=90)
    deploy_ts = culprit_ts + dt.timedelta(minutes=2)
    onset = deploy_ts + dt.timedelta(minutes=1)
    fired = onset + dt.timedelta(minutes=3)

    commits = []
    pool = INNOCENT[:]
    rng.shuffle(pool)
    for i in range(args.distractors):
        msg, files = pool[i % len(pool)]
        ts = base + dt.timedelta(seconds=rng.randint(0, 3 * 3600))
        commits.append({"sha": sha(rng), "author": f"dev{i%7}", "timestamp": iso(ts),
                        "message": msg, "files_changed": files})
    culprit = {"sha": sha(rng), "author": "culprit.dev", "timestamp": iso(culprit_ts),
               "message": args.culprit_message, "files_changed": args.culprit_files}
    # an innocent decoy deployed just before onset
    decoy = {"sha": sha(rng), "author": "innocent.dev",
             "timestamp": iso(deploy_ts + dt.timedelta(seconds=20)),
             "message": "feat(frontend): restyle banner", "files_changed": ["services/frontend/static/banner.css"]}
    commits += [culprit, decoy]
    commits.sort(key=lambda c: c["timestamp"])

    deploys = [
        {"timestamp": iso(deploy_ts), "service": args.service,
         "commit_sha": culprit["sha"], "version": "v2026.01.01-1"},
        {"timestamp": iso(deploy_ts + dt.timedelta(seconds=40)), "service": "frontend",
         "commit_sha": decoy["sha"], "version": "v2026.01.01-2"},
    ]
    flags = [{"timestamp": iso(onset - dt.timedelta(minutes=5)), "flag": "some_new_flag",
              "service": args.service, "change": "off->on", "actor": "flag.dev"}]
    alert = {"service": args.service, "metric": "error_rate_5xx_ratio", "threshold": 0.02,
             "observed": 0.5, "fired_at": iso(fired), "severity": "critical",
             "monitor": f"{args.service}-alert", "summary": f"{args.service} regression"}

    tid = lambda: "".join(rng.choice("0123456789abcdef") for _ in range(32))
    logs = [{"timestamp": iso(base + dt.timedelta(minutes=m)), "service": args.service,
             "severity_text": "INFO", "msg": "ok", "trace_id": tid()} for m in range(0, 60, 2)]
    for _ in range(20):
        logs.append({"timestamp": iso(onset + dt.timedelta(seconds=rng.randint(0, 300))),
                     "service": args.service, "severity_text": "ERROR",
                     "msg": "FIXME: replace with your failure signature", "trace_id": tid()})
    logs.sort(key=lambda r: r["timestamp"])

    mrows = []
    cur = base
    while cur <= fired + dt.timedelta(minutes=5):
        post = cur >= onset
        mrows.append([iso(cur), args.service, "error_rate_5xx_ratio",
                      round(0.5 if post else 0.002, 4)])
        cur += dt.timedelta(minutes=1)

    traces = [{"trace_id": tid(), "span_id": "a1", "parent_id": None, "service": args.service,
               "name": "Handle", "start": iso(onset), "duration_ms": 10, "status": "ERROR"}]
    patterns = [{"signature": "FIXME: replace with your failure signature", "service": args.service,
                 "count": 100, "delta_vs_baseline": "+100", "sentiment": "negative"}]

    gt = {"scenario": args.name, "root_cause_commit": culprit["sha"],
          "first_failing_service": args.service, "blast_radius": args.blast,
          "remediation": args.remediation, "decoy_deploy_commits": [decoy["sha"]],
          "notes": "FIXME: describe the fault and why the decoy is innocent."}

    def wj(p, o):
        with open(p, "w") as f:
            json.dump(o, f, indent=2); f.write("\n")

    wj(os.path.join(data, "alert.json"), alert)
    with open(os.path.join(data, "logs.ndjson"), "w") as f:
        for r in logs:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(data, "metrics.csv"), "w") as f:
        f.write("timestamp,service,metric,value\n")
        for r in mrows:
            f.write(",".join(str(x) for x in r) + "\n")
    wj(os.path.join(data, "traces.json"), traces)
    wj(os.path.join(data, "patterns.json"), patterns)
    wj(os.path.join(data, "context", "commits.json"), commits)
    wj(os.path.join(data, "context", "deploys.json"), deploys)
    wj(os.path.join(data, "context", "flags.json"), flags)
    wj(os.path.join(sdir, "tests", "ground_truth.json"), gt)

    # Reuse shared test wiring + Dockerfile from the template scenario.
    for rel in ["tests/test.sh", "tests/test_outputs.py", "environment/Dockerfile"]:
        shutil.copy(os.path.join(TEMPLATE, rel), os.path.join(sdir, rel))

    # Minimal task.toml + instruction.md + solve.sh
    with open(os.path.join(sdir, "task.toml"), "w") as f:
        f.write(f'''version = "1.0"

[metadata]
author_name = "Edge Delta"
author_email = "oss@edgedelta.com"
difficulty = "{args.difficulty}"
category = "observability"
tags = ["root-cause", "observability", "incident"]

[verifier]
timeout_sec = 120.0

[agent]
timeout_sec = 3600.0

[environment]
build_timeout_sec = 600.0
cpus = 2
memory_mb = 4096
storage_mb = 8192
''')
    with open(os.path.join(sdir, "instruction.md"), "w") as f:
        f.write(f"# Root-Cause Analysis: {args.name}\n\n"
                "See datasets/rootcausebench/README.md for the data schema. Read "
                "`/workdir/data/`, find the culprit commit, and write "
                "`/workdir/root_cause.json` + `/workdir/reasoning.md`.\n\n"
                "FIXME: copy the full instruction body from a shipped scenario "
                "and fill in the symptom + signal hint.\n")
    sp = os.path.join(sdir, "solution", "solve.sh")
    with open(sp, "w") as f:
        ans = {"root_cause_commit": culprit["sha"], "first_failing_service": args.service,
               "blast_radius": args.blast, "remediation": args.remediation}
        f.write("#!/bin/bash\nset -e\nmkdir -p /workdir\n"
                f"cat > /workdir/root_cause.json << 'EOF'\n{json.dumps(ans, indent=2)}\nEOF\n"
                "echo 'oracle answer written'\n")
    os.chmod(sp, 0o755)

    print(f"Scaffolded scenario at {sdir}")
    print(f"Culprit SHA: {culprit['sha']}")
    print("Next: hand-edit the telemetry to add a real failure signature, then "
          "validate with the oracle (solution/solve.sh) against tests/test_outputs.py.")


if __name__ == "__main__":
    main()
