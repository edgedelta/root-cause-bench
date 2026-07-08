#!/usr/bin/env python3
"""Non-LLM baselines for RootCauseBench: can a script name the culprit commit?

A benchmark whose culprit can be found by a trivial policy measures nothing.
Five deterministic baselines answer every scenario using only the data the
agent sees (alert.json + context/{commits,deploys}.json) and are scored with
the grader's primary rule (exact culprit SHA match; "none" for no-code-cause):

  latest-commit          blame the newest commit in commits.json
  always-none            answer "none" every time (the no-code-cause prior)
  latest-deploy          blame the last deploy before alert onset — the classic
                         3am heuristic the decoy deploys are designed to catch
  alert-service-deploy   blame the last pre-onset deploy to the alerting service
  scripted-rca           ~20-line heuristic: score pre-onset deployed commits by
                         service match + alert-keyword hits in the diff, most
                         recent wins; answer "none" if nothing scores

Writes benchmark-results/rootcausebench/baselines.json. With --check (CI mode)
it fails if `latest-commit` passes any scenario (culprit == newest commit means
the scenario is trivially gameable) and warns when a cheap deploy-blaming
heuristic passes a real-culprit scenario.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATASET = REPO / "datasets" / "rootcausebench"
OUT_PATH = REPO / "benchmark-results" / "rootcausebench" / "baselines.json"

CHEAP = ("latest-deploy", "alert-service-deploy", "scripted-rca")


# --- baseline policies -----------------------------------------------------
# Each returns the SHA to blame (or "none"), given the visible data.

def latest_commit(alert, commits, deploys):
    return max(commits, key=lambda c: c["timestamp"])["sha"]


def always_none(alert, commits, deploys):
    return "none"


def _pre_onset(deploys, alert):
    fired = alert["fired_at"]
    return [d for d in deploys if d["timestamp"] <= fired]


def latest_deploy(alert, commits, deploys):
    pre = _pre_onset(deploys, alert)
    if not pre:
        return "none"
    return max(pre, key=lambda d: d["timestamp"])["commit_sha"]


def alert_service_deploy(alert, commits, deploys):
    pre = [d for d in _pre_onset(deploys, alert) if d["service"] == alert["service"]]
    if not pre:
        return "none"
    return max(pre, key=lambda d: d["timestamp"])["commit_sha"]


def scripted_rca(alert, commits, deploys):
    """Score pre-onset deployed commits: service match + alert keywords in diff."""
    by_sha = {c["sha"]: c for c in commits}
    keywords = {w.lower() for w in
                [alert.get("service", ""), alert.get("metric", "")] if w}
    for word in (alert.get("summary", "") + " " + alert.get("detail", "")).split():
        w = word.strip(".,:;'\"()").lower()
        if len(w) > 6:
            keywords.add(w)
    best_sha, best_score, best_ts = "none", 0, ""
    for dep in _pre_onset(deploys, alert):
        c = by_sha.get(dep["commit_sha"])
        if not c:
            continue
        hay = ((c.get("diff") or "") + " " + " ".join(c.get("files_changed") or [])).lower()
        score = 2 * (dep["service"] == alert["service"])
        score += sum(1 for k in keywords if k in hay)
        if score > best_score or (score == best_score > 0 and dep["timestamp"] > best_ts):
            best_sha, best_score, best_ts = dep["commit_sha"], score, dep["timestamp"]
    return best_sha


BASELINES = {
    "latest-commit": latest_commit,
    "always-none": always_none,
    "latest-deploy": latest_deploy,
    "alert-service-deploy": alert_service_deploy,
    "scripted-rca": scripted_rca,
}


# --- scoring (mirrors the grader's primary rule) -----------------------------

def score(sha, gt):
    want = gt["root_cause_commit"].strip().lower()
    got = (sha or "").strip().lower()
    passed = got == want or (want != "none" and len(got) >= 7 and want.startswith(got))
    return {
        "passed": passed,
        "answered": got[:12],
        "hit_decoy": got in {s.lower() for s in gt.get("decoy_deploy_commits", [])},
    }


def load_scenario(d):
    data = d / "environment" / "data"
    difficulty, tags = "?", []
    for line in (d / "task.toml").read_text().splitlines():
        s = line.strip()
        if s.startswith("difficulty"):
            difficulty = s.split("=")[1].strip().strip('"')
        elif s.startswith("tags"):
            tags = [t.strip().strip('"') for t in s.split("=", 1)[1].strip(" []").split(",")]
    return {
        "alert": json.loads((data / "alert.json").read_text()),
        "commits": json.loads((data / "context" / "commits.json").read_text()),
        "deploys": json.loads((data / "context" / "deploys.json").read_text()),
        "gt": json.loads((d / "tests" / "ground_truth.json").read_text()),
        "difficulty": difficulty,
        "no_code_cause": "no-code-cause" in tags,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="CI mode: fail if latest-commit passes any scenario")
    args = ap.parse_args()

    scenarios = sorted(p for p in DATASET.iterdir()
                       if (p / "tests" / "ground_truth.json").exists())
    results = {name: {} for name in BASELINES}
    meta = {}
    for d in scenarios:
        data = load_scenario(d)
        meta[d.name] = data
        for name, policy in BASELINES.items():
            r = score(policy(data["alert"], data["commits"], data["deploys"]), data["gt"])
            r["difficulty"] = data["difficulty"]
            r["no_code_cause"] = data["no_code_cause"]
            results[name][d.name] = r

    width = max(len(d.name) for d in scenarios)
    header = (f"{'scenario':<{width}}  {'tier':<6}  kind  "
              + "  ".join(f"{n:>20}" for n in BASELINES))
    print(header)
    print("-" * len(header))
    for d in scenarios:
        cells = []
        for name in BASELINES:
            r = results[name][d.name]
            mark = "PASS" if r["passed"] else ("decoy" if r["hit_decoy"] else "fail")
            cells.append(f"{mark}".rjust(20))
        kind = "none" if meta[d.name]["no_code_cause"] else "code"
        print(f"{d.name:<{width}}  {meta[d.name]['difficulty']:<6}  {kind:<4}  " + "  ".join(cells))

    print()
    summary = {}
    tier_names = sorted({m["difficulty"] for m in meta.values()})
    for name in BASELINES:
        rs = results[name]
        passed = sum(r["passed"] for r in rs.values())
        decoys = sum(r["hit_decoy"] for r in rs.values())
        by_tier = {t: f"{sum(r['passed'] for s, r in rs.items() if r['difficulty'] == t)}"
                      f"/{sum(1 for r in rs.values() if r['difficulty'] == t)}"
                   for t in tier_names}
        summary[name] = {"passed": passed, "total": len(scenarios),
                         "pass_rate_pct": round(100 * passed / len(scenarios), 1),
                         "decoy_hits": decoys, "by_tier": by_tier}
        tier_str = "  ".join(f"{t} {by_tier[t]}" for t in tier_names)
        print(f"{name:>20}: {passed}/{len(scenarios)} passed, {decoys} decoy hits  ({tier_str})")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(
        {"summary": summary, "by_scenario": results}, indent=2) + "\n")
    print(f"\nwrote {OUT_PATH.relative_to(REPO)}")

    if args.check:
        for n in CHEAP:
            for s, r in results[n].items():
                if r["passed"] and not r["no_code_cause"]:
                    print(f"WARNING: cheap heuristic '{n}' names the culprit in {s} — "
                          f"the scenario is solvable without reading the diff.")
        hard_fails = [s for s, r in results["latest-commit"].items() if r["passed"]]
        if hard_fails:
            print(f"CI FAIL: 'latest-commit' passes {hard_fails} — culprit is the newest "
                  f"commit; trivially gameable.")
            sys.exit(1)
        print("CI OK: no degenerate baseline passes any scenario.")


if __name__ == "__main__":
    main()
