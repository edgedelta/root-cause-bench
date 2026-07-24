"""Generate logs/metrics/traces/patterns from a validated spec."""
from __future__ import annotations

import hashlib
import random
import re
from datetime import timedelta

from .spec import fmt_ts, parse_ts


def _trace_id(spec_name: str, ident: str) -> str:
    return hashlib.md5(f"{spec_name}:{ident}".encode()).hexdigest()


def build_logs(spec: dict) -> list[dict]:
    rng = random.Random(spec["seed"] + 1)
    w = spec["window"]
    start, end = parse_ts(w["start"]), parse_ts(w["end"])
    total_s = (end - start).total_seconds()
    rows = []

    weights = [(svc, svc["log_weight"]) for svc in spec["services"] if svc["logs"]]
    n_baseline = int(total_s * w["log_rps"]) if weights else 0
    for i in range(n_baseline):
        svc = rng.choices([s for s, _ in weights],
                          [wt for _, wt in weights])[0]
        line = rng.choices(svc["logs"], [l["weight"] for l in svc["logs"]])[0]
        ts = start + timedelta(seconds=rng.uniform(0, total_s))
        rows.append({
            "timestamp": fmt_ts(ts), "service": svc["name"],
            "severity_text": line["severity"], "msg": line["msg"],
            "trace_id": _trace_id(spec["name"], f"log:{i}"),
            **line["extra"],
        })

    for j, lf in enumerate(spec["incident"]["log_faults"]):
        f_start, f_end = parse_ts(lf["start"]), parse_ts(lf["end"])
        step = 60.0 / lf["rate_per_min"]
        k, t = 0, f_start
        while t < f_end:
            rows.append({
                "timestamp": fmt_ts(t), "service": lf["service"],
                "severity_text": lf["severity"], "msg": lf["msg"],
                "trace_id": _trace_id(spec["name"], f"fault:{j}:{k}"),
                **lf["extra"],
            })
            k += 1
            t = f_start + timedelta(seconds=step * k)

    rows.sort(key=lambda r: (r["timestamp"], r["service"], r["msg"]))
    return rows


def build_metrics(spec: dict) -> list[dict]:
    rng = random.Random(spec["seed"] + 2)
    w = spec["window"]
    start, end = parse_ts(w["start"]), parse_ts(w["end"])
    step = timedelta(seconds=w["metric_step_s"])
    faults = {(mf["service"], mf["metric"]): mf
              for mf in spec["incident"]["metric_faults"]}
    rows = []
    for svc in spec["services"]:
        for m in svc["metrics"]:
            fault = faults.get((svc["name"], m["name"]))
            t = start
            while t <= end:
                base = m["baseline"] * (1 + rng.uniform(-m["jitter"], m["jitter"]))
                value = base
                if fault:
                    fs, fe = parse_ts(fault["start"]), parse_ts(fault["end"])
                    if t >= fs:
                        if fault["curve"] == "step":
                            value = fault["to"]
                        else:  # ramp
                            frac = min(1.0, (t - fs) / (fe - fs)) if fe > fs else 1.0
                            value = m["baseline"] + (fault["to"] - m["baseline"]) * frac
                rows.append({"timestamp": fmt_ts(t), "service": svc["name"],
                             "metric": m["name"], "value": round(value, 1)})
                t += step
    rows.sort(key=lambda r: (r["timestamp"], r["service"], r["metric"]))
    return rows


def build_traces(spec: dict) -> list[dict]:
    w = spec["window"]
    start, end = parse_ts(w["start"]), parse_ts(w["end"])
    hours = (end - start).total_seconds() / 3600
    spans = []
    for flow in spec["trace_flows"]:
        n = int(flow["per_hour"] * hours)
        for i in range(n):
            tid = _trace_id(spec["name"], f"flow:{flow['name']}:{i}")
            t0 = start + (end - start) * (i / max(1, n))
            parent = None
            for k, sp in enumerate(flow["spans"]):
                spans.append({
                    "trace_id": tid, "span_id": f"s{k}", "parent_id": parent,
                    "service": sp["service"], "name": sp["name"],
                    "start": fmt_ts(t0), "duration_ms": sp["duration_ms"],
                    "status": "OK",
                })
                parent = f"s{k}"
    spans.extend(spec["incident"]["trace_exemplars"])
    return spans


def build_patterns(spec: dict, logs: list[dict]) -> list[dict]:
    pats = []
    for lf in spec["incident"]["log_faults"]:
        sig = re.sub(r"\d+", "<N>", lf["msg"])
        count = sum(1 for r in logs
                    if r["msg"] == lf["msg"] and r["service"] == lf["service"])
        pats.append({"signature": sig, "service": lf["service"], "count": count,
                     "delta_vs_baseline": f"+{count}", "sentiment": "negative"})
    for svc in spec["services"]:
        if not svc["logs"]:
            continue
        top = max(svc["logs"], key=lambda l: l["weight"])
        count = sum(1 for r in logs
                    if r["msg"] == top["msg"] and r["service"] == svc["name"])
        if count:
            pats.append({"signature": re.sub(r"\d+", "<N>", top["msg"]),
                         "service": svc["name"], "count": count,
                         "delta_vs_baseline": "+0", "sentiment": "neutral"})
    return pats
