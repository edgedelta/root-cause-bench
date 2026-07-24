"""Emit a complete Terminal-Bench scenario directory from a scenario.toml."""
from __future__ import annotations

import csv
import io
import json
import shutil
from datetime import timedelta
from pathlib import Path

from .changes import build_changes
from .degrade import apply_degradations
from .spec import SpecError, load_spec, parse_ts
from .telemetry import build_logs, build_metrics, build_patterns, build_traces

REPO = Path(__file__).resolve().parent.parent.parent
TEMPLATE = REPO / "datasets" / "rootcausebench" / "payment-nil-deref-panic"
INSTRUCTION_TEMPLATE = Path(__file__).parent / "templates" / "instruction.md"

TASK_TOML = '''version = "1.0"

[metadata]
author_name = "Edge Delta"
author_email = "oss@edgedelta.com"
difficulty = "{difficulty}"
category = "{category}"
tags = [{tags}]

[verifier]
timeout_sec = 120.0

[agent]
timeout_sec = 5400.0

[environment]
build_timeout_sec = 600.0
cpus = 2
memory_mb = 4096
storage_mb = 8192
'''

SOLVE_SH = '''#!/bin/bash
# ORACLE solution for {name}.
# Writes the known-correct answer so we can validate the grader.
set -e

mkdir -p /workdir

cat > /workdir/root_cause.json << 'EOF'
{answer}
EOF

cat > /workdir/reasoning.md << 'EOF'
# Root cause: {name}

{notes}
EOF

echo "Oracle answer written to /workdir/root_cause.json"
cat /workdir/root_cause.json
'''


def _check_consistency(spec: dict, commits, deploys, id_to_sha):
    errs = []
    onset = parse_ts(spec["incident"]["onset"])
    fired = parse_ts(spec["alert"]["fired_at"])
    end = parse_ts(spec["window"]["end"])
    if not (onset <= fired <= end):
        errs.append("alert.fired_at must satisfy onset <= fired_at <= window.end")
    if spec["alert"]["service"] not in {s["name"] for s in spec["services"]}:
        errs.append(f"alert.service {spec['alert']['service']!r} not in services")

    culprit_id = spec["ground_truth"]["culprit_id"]
    culprit_sha = id_to_sha.get(culprit_id)
    for d in deploys:
        if culprit_sha and d["commit_sha"] == culprit_sha \
                and parse_ts(d["timestamp"]) > onset:
            errs.append(f"culprit deploy at {d['timestamp']} is after onset "
                        f"{spec['incident']['onset']}")
    near = [d for d in deploys
            if d["commit_sha"] != culprit_sha
            and timedelta(0) <= fired - parse_ts(d["timestamp"])
            <= timedelta(minutes=15)]
    if not near:
        errs.append("no non-culprit deploy within 15min before fired_at "
                    "(decoy-position invariant)")

    shas = {c["sha"] for c in commits}
    for d in deploys:
        if d["commit_sha"] not in shas:
            errs.append(f"deploy commit {d['commit_sha'][:12]} not in commits.json")
    for label, ref in [("culprit", spec["ground_truth"]["culprit_id"]),
                       *(("decoy", d) for d in spec["ground_truth"]["decoy_ids"])]:
        if ref != "none" and id_to_sha.get(ref) not in shas:
            errs.append(f"{label} id {ref!r} does not resolve into commits.json")

    if errs:
        raise SpecError("consistency: " + "; ".join(errs))


def emit_scenario(spec_path: Path) -> Path:
    spec_path = Path(spec_path)
    spec = load_spec(spec_path)
    out = spec_path.parent
    keep = {out / rel for rel in spec["overrides"]["keep"]}

    commits, deploys, flags, id_to_sha = build_changes(spec)
    logs = build_logs(spec)
    metrics = build_metrics(spec)
    traces = build_traces(spec)
    logs, metrics, traces = apply_degradations(spec, logs, metrics, traces)
    patterns = build_patterns(spec, logs)
    _check_consistency(spec, commits, deploys, id_to_sha)

    def write(rel: str, content: str):
        p = out / rel
        if p in keep and p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def copy(rel: str):
        p = out / rel
        if p in keep and p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(TEMPLATE / rel, p)

    write("task.toml", TASK_TOML.format(
        difficulty=spec["difficulty"], category=spec["category"],
        tags=", ".join(f'"{t}"' for t in spec["tags"])))
    write("instruction.md", INSTRUCTION_TEMPLATE.read_text())
    for rel in ("environment/Dockerfile",
                "tests/test.sh", "tests/test_outputs.py"):
        copy(rel)

    write("environment/data/alert.json", json.dumps(spec["alert"], indent=1) + "\n")
    write("environment/data/logs.ndjson",
          "".join(json.dumps(r) + "\n" for r in logs))
    buf = io.StringIO()
    cw = csv.writer(buf)
    cw.writerow(["timestamp", "service", "metric", "value"])
    for r in metrics:
        cw.writerow([r["timestamp"], r["service"], r["metric"], r["value"]])
    write("environment/data/metrics.csv", buf.getvalue())
    write("environment/data/traces.json", json.dumps(traces, indent=1) + "\n")
    write("environment/data/patterns.json", json.dumps(patterns, indent=1) + "\n")
    write("environment/data/context/commits.json",
          json.dumps(commits, indent=1) + "\n")
    write("environment/data/context/deploys.json",
          json.dumps(deploys, indent=1) + "\n")
    write("environment/data/context/flags.json", json.dumps(flags, indent=1) + "\n")

    gt = spec["ground_truth"]
    culprit_sha = "none" if gt["culprit_id"] == "none" else id_to_sha[gt["culprit_id"]]
    ground_truth = {
        "scenario": spec["name"],
        "root_cause_commit": culprit_sha,
        "first_failing_service": spec["incident"]["first_failing_service"],
        "blast_radius": gt["blast_radius"],
        "remediation": gt["remediation"],
        "decoy_deploy_commits": [id_to_sha[d] for d in gt["decoy_ids"]],
        "notes": gt["notes"],
    }
    write("tests/ground_truth.json", json.dumps(ground_truth, indent=1) + "\n")

    answer = json.dumps({
        "root_cause_commit": culprit_sha,
        "first_failing_service": ground_truth["first_failing_service"],
        "blast_radius": ground_truth["blast_radius"],
        "remediation": ground_truth["remediation"],
    }, indent=2)
    write("solution/solve.sh",
          SOLVE_SH.format(name=spec["name"], answer=answer, notes=gt["notes"]))
    (out / "solution/solve.sh").chmod(0o755)
    return out
