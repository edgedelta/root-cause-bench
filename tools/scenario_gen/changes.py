"""Expand spec commits/deploys/flags into the context/*.json payloads."""
from __future__ import annotations

import hashlib
import random
from datetime import timedelta

from .spec import fmt_ts, parse_ts

# Innocent-commit pool: (message, files, small plausible diff or None).
# Messages are deliberately mundane and never fault-describing.
INNOCENT_POOL = [
    ("chore: bump go.mod dependencies", ["go.mod", "go.sum"], None),
    ("docs: update API reference", ["docs/api/orders.md"], None),
    ("test: add table-driven tests for money conversion",
     ["pkg/money/convert_test.go"], None),
    ("refactor: extract response writer helper",
     ["internal/httputil/writer.go"],
     "--- a/internal/httputil/writer.go\n+++ b/internal/httputil/writer.go\n"
     "@@ -10,6 +10,10 @@\n+func writeJSON(w http.ResponseWriter, code int, v any) {\n"
     "+\tw.WriteHeader(code)\n+\t_ = json.NewEncoder(w).Encode(v)\n+}\n"),
    ("ci: cache go build artifacts", [".github/workflows/build.yml"], None),
    ("feat: add structured logging fields", ["internal/middleware/log.go"],
     "--- a/internal/middleware/log.go\n+++ b/internal/middleware/log.go\n"
     "@@ -22,7 +22,8 @@\n-\tlogger.Info(\"request\")\n"
     "+\tlogger.Info(\"request\", \"route\", r.URL.Path, \"ms\", elapsed)\n"),
    ("fix: correct typo in error message", ["internal/errors/messages.go"],
     "--- a/internal/errors/messages.go\n+++ b/internal/errors/messages.go\n"
     "@@ -4,1 +4,1 @@\n-\t\"unkown resource\"\n+\t\"unknown resource\"\n"),
    ("perf: preallocate buffer in JSON encoder", ["pkg/codec/json.go"], None),
    ("feat: add /readyz endpoint", ["internal/health/ready.go"], None),
    ("refactor: simplify config loading", ["internal/config/load.go"], None),
    ("chore: regenerate protobuf stubs", ["pkg/pb/orders.pb.go"], None),
    ("docs: onboarding notes for new services", ["docs/onboarding.md"], None),
    ("test: raise coverage threshold", ["Makefile"], None),
    ("style: gofmt sweep", ["internal/worker/pool.go"], None),
    ("feat: expose build info endpoint", ["internal/health/version.go"], None),
    ("chore: rotate lint config", [".golangci.yml"], None),
]

AUTHORS = ["lena.fischer", "marco.silva", "priya.nair", "tom.oduya",
           "sofia.rossi", "jan.kowalski", "mei.chen", "ahmet.yilmaz"]


def _sha(name: str, ident: str) -> str:
    return hashlib.sha1(f"{name}:{ident}".encode()).hexdigest()


def _default_version(ts_str: str) -> str:
    return ("v" + ts_str[:10].replace("-", ".") + "-" + ts_str[11:16].replace(":", ""))


def _pick_innocent_commit(rng: random.Random, ts, innocent_commits: list[dict]):
    """Pick an innocent commit authored strictly before `ts` (a datetime).

    If none is eligible, shift `ts` to 5-40 minutes after the earliest
    innocent commit so at least that commit becomes eligible.
    """
    eligible = [c for c in innocent_commits if parse_ts(c["timestamp"]) < ts]
    if not eligible:
        earliest = min(innocent_commits, key=lambda c: c["timestamp"])
        ts = parse_ts(earliest["timestamp"]) + timedelta(minutes=rng.randint(5, 40))
        eligible = [c for c in innocent_commits if parse_ts(c["timestamp"]) < ts]
    return ts, rng.choice(eligible)


def build_changes(spec: dict) -> tuple[list[dict], list[dict], list[dict], dict[str, str]]:
    name = spec["name"]
    rng = random.Random(spec["seed"])
    w = spec["window"]
    start, end = parse_ts(w["start"]), parse_ts(w["end"])
    authored = spec["commits"]["authored"]

    id_to_sha = {a["id"]: _sha(name, a["id"]) for a in authored}
    commits = [{
        "sha": id_to_sha[a["id"]],
        "author": a["author"],
        "timestamp": a["timestamp"],
        "message": a["message"],
        "files_changed": list(a["files"]),
        "diff": a["diff"],
    } for a in authored]

    latest_authored = max((parse_ts(a["timestamp"]) for a in authored),
                          default=start)
    n = spec["commits"]["innocent_count"]
    span = (end - start).total_seconds()
    for i in range(n):
        msg, files, diff = INNOCENT_POOL[i % len(INNOCENT_POOL)]
        if i == n - 1:  # newest commit is always innocent (latest-commit gate)
            ts = min(end, latest_authored + timedelta(minutes=rng.randint(3, 20)))
        else:
            ts = start + timedelta(seconds=rng.uniform(0, span * 0.95))
        commits.append({
            "sha": _sha(name, f"innocent:{i}"),
            "author": rng.choice(AUTHORS),
            "timestamp": fmt_ts(ts),
            "message": msg,
            "files_changed": list(files),
            "diff": diff,
        })
    commits.sort(key=lambda c: (c["timestamp"], c["sha"]))

    authored_shas = set(id_to_sha.values())
    innocent_commits = [c for c in commits if c["sha"] not in authored_shas]

    deploys = [{
        "timestamp": d["timestamp"],
        "service": d["service"],
        "commit_sha": id_to_sha[d["commit"]],
        "version": d["version"],
    } for d in spec["deploys"]]

    da = spec["deploys_auto"]
    count = da["count"]
    if count:
        rng3 = random.Random(spec["seed"] + 3)
        services = list(da["services"])
        shuffled_services = list(services)
        rng3.shuffle(shuffled_services)
        onset = parse_ts(spec["incident"]["onset"])

        generated = []
        for i in range(count):
            service = (shuffled_services[i] if i < len(shuffled_services)
                       else rng3.choice(services))
            ts = start + timedelta(seconds=rng3.uniform(0, span))
            ts, commit = _pick_innocent_commit(rng3, ts, innocent_commits)
            generated.append({"ts": ts, "service": service, "commit": commit})

        pre_onset_min = da["pre_onset_min"]
        before = sum(1 for g in generated if g["ts"] < onset)
        if before < pre_onset_min:
            shortfall = pre_onset_min - before
            onset_span = (onset - start).total_seconds()
            for g in generated:
                if shortfall <= 0:
                    break
                if g["ts"] >= onset:
                    new_ts = start + timedelta(seconds=rng3.uniform(0, onset_span))
                    new_ts, commit = _pick_innocent_commit(rng3, new_ts, innocent_commits)
                    g["ts"], g["commit"] = new_ts, commit
                    shortfall -= 1

        for g in generated:
            ts_str = fmt_ts(g["ts"])
            deploys.append({
                "timestamp": ts_str,
                "service": g["service"],
                "commit_sha": g["commit"]["sha"],
                "version": _default_version(ts_str),
            })

    deploys.sort(key=lambda d: d["timestamp"])

    return commits, deploys, list(spec["flags"]), id_to_sha
