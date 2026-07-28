"""Apply spec degradation directives to generated telemetry (never to context)."""
from __future__ import annotations

import copy
import hashlib
from datetime import timedelta

from .spec import fmt_ts, parse_ts


def _skew(rows: list[dict], key: str, offset_s: float, service: str | None):
    for r in rows:
        if service is None or r.get("service") == service:
            r[key] = fmt_ts(parse_ts(r[key]) + timedelta(seconds=offset_s))
    return rows


def apply_degradations(spec, logs, metrics, traces):
    logs = copy.deepcopy(logs)
    metrics = copy.deepcopy(metrics)
    traces = copy.deepcopy(traces)
    for deg in spec.get("degradations", []):
        t = deg["type"]
        if t == "drop_logs":
            logs = [r for r in logs
                    if not (r["service"] == deg["service"]
                            and r["timestamp"] >= deg["after"])]
        elif t == "clock_skew":
            target, off, svc = deg["target"], deg["offset_s"], deg.get("service")
            if target == "logs":
                logs = _skew(logs, "timestamp", off, svc)
            elif target == "metrics":
                metrics = _skew(metrics, "timestamp", off, svc)
            elif target == "traces":
                traces = _skew(traces, "start", off, svc)
        elif t == "sample_traces":
            cut = int(deg["rate"] * 10_000)
            traces = [sp for sp in traces
                      if int(hashlib.md5(sp["trace_id"].encode()).hexdigest(),
                             16) % 10_000 < cut]
    return logs, metrics, traces
