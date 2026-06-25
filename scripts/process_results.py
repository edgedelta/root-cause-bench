#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Process raw Harbor result.json files into a per-model accuracy table.

PRIMARY reward in RootCauseBench is binary: did the model name the exact
culprit commit? This script aggregates that reward across attempts and prints:
  1. an overall per-model accuracy table (markdown)
  2. a per-difficulty breakdown (easy / medium / hard)

Usage:
    uv run scripts/process_results.py jobs/2026-06-25__14-00-00 [more_job_dirs ...]

It reads <job_dir>/*/result.json (Harbor's standard layout). Difficulty is read
from each scenario's task.toml under datasets/.
"""
from __future__ import annotations

import json
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS = REPO_ROOT / "datasets"


def scenario_difficulty(task_name: str) -> str:
    """task_name looks like 'rootcausebench/<scenario>'."""
    toml_path = DATASETS / task_name / "task.toml"
    if not toml_path.exists():
        # task_name may already be just the scenario leaf
        toml_path = DATASETS / "rootcausebench" / task_name / "task.toml"
    if not toml_path.exists():
        return "unknown"
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    return data.get("metadata", {}).get("difficulty", "unknown")


def model_of(raw: dict) -> str:
    return raw.get("config", {}).get("agent", {}).get("model_name", "unknown").split("/")[-1]


def reward_of(raw: dict) -> float:
    return (raw.get("verifier_result") or {}).get("rewards", {}).get("reward", 0.0)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    result_files: list[Path] = []
    for jd in sys.argv[1:]:
        p = Path(jd)
        if not p.is_dir():
            print(f"warning: {p} is not a directory", file=sys.stderr)
            continue
        result_files.extend(sorted(p.glob("*/result.json")))

    if not result_files:
        print("No result.json files found.", file=sys.stderr)
        sys.exit(1)

    # (model, difficulty) -> [rewards]; (model,) -> [rewards]
    by_model: dict[str, list[float]] = defaultdict(list)
    by_model_diff: dict[tuple[str, str], list[float]] = defaultdict(list)

    for rf in result_files:
        try:
            raw = json.loads(rf.read_text())
        except Exception as e:  # noqa: BLE001
            print(f"  parse error {rf}: {e}", file=sys.stderr)
            continue
        if raw.get("exception_info"):
            continue
        model = model_of(raw)
        task = raw.get("task_name", "")
        diff = scenario_difficulty(task)
        r = 1.0 if reward_of(raw) > 0 else 0.0
        by_model[model].append(r)
        by_model_diff[(model, diff)].append(r)

    models = sorted(by_model)
    diffs = ["easy", "medium", "hard"]

    print("\n## RootCauseBench results — culprit-commit accuracy\n")
    print("| Model | Overall | n |")
    print("|-------|---------|---|")
    for m in models:
        rs = by_model[m]
        acc = 100 * sum(rs) / len(rs) if rs else 0.0
        print(f"| {m} | {acc:.0f}% | {len(rs)} |")

    print("\n### Per-difficulty breakdown\n")
    header = "| Model | " + " | ".join(d for d in diffs) + " |"
    print(header)
    print("|" + "---|" * (len(diffs) + 1))
    for m in models:
        cells = []
        for d in diffs:
            rs = by_model_diff.get((m, d), [])
            cells.append(f"{100*sum(rs)/len(rs):.0f}% (n={len(rs)})" if rs else "—")
        print(f"| {m} | " + " | ".join(cells) + " |")
    print()


if __name__ == "__main__":
    main()
