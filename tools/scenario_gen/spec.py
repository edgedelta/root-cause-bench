"""Load + validate a scenario.toml spec into a plain dict with defaults."""
from __future__ import annotations

import tomllib
from datetime import datetime, timezone
from pathlib import Path

FAMILIES = {"guilty-decoy", "beyond-context", "degraded-telemetry"}
CURVES = {"step", "ramp"}
DEGRADATIONS = {"drop_logs", "clock_skew", "sample_traces"}
REMEDIATIONS = {"rollback", "roll-forward", "config-revert", "scale",
                "feature-flag-disable"}


class SpecError(ValueError):
    pass


def parse_ts(s: str) -> datetime:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise SpecError(f"bad timestamp {s!r} (want YYYY-MM-DDTHH:MM:SSZ)")


def fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _req(d: dict, key: str, where: str):
    if key not in d:
        raise SpecError(f"{where}: missing required key {key!r}")
    return d[key]


def load_spec(path: Path) -> dict:
    with open(path, "rb") as f:
        spec = tomllib.load(f)

    for key in ("name", "family", "seed", "window", "alert", "services",
                "incident", "commits", "deploys", "ground_truth"):
        _req(spec, key, "spec")

    if spec["family"] not in FAMILIES:
        raise SpecError(f"family {spec['family']!r} not in {sorted(FAMILIES)}")

    spec.setdefault("difficulty", "adversarial")
    spec.setdefault("category", "observability")
    base_tags = ["root-cause", "adversarial", spec["family"], "observability",
                 "incident"]
    spec["tags"] = base_tags + [t for t in spec.get("tags", []) if t not in base_tags]
    spec.setdefault("flags", [])
    spec.setdefault("degradations", [])
    spec.setdefault("trace_flows", [])
    spec.setdefault("overrides", {}).setdefault("keep", [])

    w = spec["window"]
    w.setdefault("metric_step_s", 60)
    w.setdefault("log_rps", 0.05)
    start, end = parse_ts(_req(w, "start", "window")), parse_ts(_req(w, "end", "window"))
    if start >= end:
        raise SpecError("window: start must precede end")

    inc = spec["incident"]
    inc.setdefault("metric_faults", [])
    inc.setdefault("log_faults", [])
    inc.setdefault("trace_exemplars", [])
    onset = parse_ts(_req(inc, "onset", "incident"))
    if not (start <= onset <= end):
        raise SpecError("incident: onset must fall inside the window")
    _req(inc, "first_failing_service", "incident")
    for mf in inc["metric_faults"]:
        mf.setdefault("curve", "ramp")
        mf.setdefault("start", inc["onset"])
        mf.setdefault("end", w["end"])
        if mf["curve"] not in CURVES:
            raise SpecError(f"metric_faults: curve {mf['curve']!r} not in {sorted(CURVES)}")
    for lf in inc["log_faults"]:
        lf.setdefault("severity", "ERROR")
        lf.setdefault("rate_per_min", 2)
        lf.setdefault("start", inc["onset"])
        lf.setdefault("end", w["end"])
        lf.setdefault("extra", {})

    for svc in spec["services"]:
        _req(svc, "name", "services")
        svc.setdefault("log_weight", 1)
        svc.setdefault("logs", [])
        svc.setdefault("metrics", [])
        for line in svc["logs"]:
            line.setdefault("severity", "INFO")
            line.setdefault("weight", 1)
            line.setdefault("extra", {})
        for m in svc["metrics"]:
            m.setdefault("jitter", 0.05)

    for flow in spec["trace_flows"]:
        flow.setdefault("per_hour", 4)
        flow.setdefault("end", w["end"])
        parse_ts(flow["end"])

    c = spec["commits"]
    c.setdefault("innocent_count", 24)
    if c["innocent_count"] < 1:
        raise SpecError("commits: innocent_count must be >= 1")
    c.setdefault("authored", [])
    ids = [a.get("id") for a in c["authored"]]
    if len(ids) != len(set(ids)) or None in ids:
        raise SpecError("commits.authored: every entry needs a unique 'id'")
    for a in c["authored"]:
        for k in ("message", "author", "timestamp", "files"):
            _req(a, k, f"commit {a['id']!r}")
        a.setdefault("diff", None)
        ts = parse_ts(a["timestamp"])
        if not (start <= ts < end):
            raise SpecError(f"commit {a['id']!r}: timestamp must be inside the "
                            f"window and strictly before window.end")

    for dep in spec["deploys"]:
        for k in ("service", "commit", "timestamp"):
            _req(dep, k, "deploys")
        parse_ts(dep["timestamp"])
        if dep["commit"] not in ids:
            raise SpecError(f"deploy references unknown commit id {dep['commit']!r}")
        dep.setdefault("version", "v" + dep["timestamp"][:10].replace("-", ".")
                       + "-" + dep["timestamp"][11:16].replace(":", ""))

    da = spec.setdefault("deploys_auto", {})
    da.setdefault("count", 0)
    da.setdefault("services", [svc["name"] for svc in spec["services"]])
    da.setdefault("pre_onset_min", 0)
    if not isinstance(da["count"], int) or isinstance(da["count"], bool) or da["count"] < 0:
        raise SpecError("deploys_auto: count must be a non-negative integer")
    if not isinstance(da["pre_onset_min"], int) or isinstance(da["pre_onset_min"], bool):
        raise SpecError("deploys_auto: pre_onset_min must be a non-negative integer")
    service_names = {svc["name"] for svc in spec["services"]}
    unknown = [s for s in da["services"] if s not in service_names]
    if unknown:
        raise SpecError(f"deploys_auto: services {unknown} not in spec services")
    if da["count"] > 0 and not da["services"]:
        raise SpecError("deploys_auto: services must be non-empty when count > 0")
    if not (0 <= da["pre_onset_min"] <= da["count"]):
        raise SpecError("deploys_auto: pre_onset_min must be between 0 and count")

    for deg in spec["degradations"]:
        if deg.get("type") not in DEGRADATIONS:
            raise SpecError(f"degradations: type {deg.get('type')!r} not in "
                            f"{sorted(DEGRADATIONS)}")

    gt = spec["ground_truth"]
    for k in ("culprit_id", "blast_radius", "remediation", "notes"):
        _req(gt, k, "ground_truth")
    gt.setdefault("decoy_ids", [])
    if gt["culprit_id"] != "none" and gt["culprit_id"] not in ids:
        raise SpecError(f"ground_truth: culprit_id {gt['culprit_id']!r} is not an "
                        f"authored commit id")
    for d in gt["decoy_ids"]:
        if d not in ids:
            raise SpecError(f"ground_truth: decoy id {d!r} is not an authored commit id")
    if gt["remediation"] not in REMEDIATIONS:
        raise SpecError(f"ground_truth: remediation {gt['remediation']!r} not in "
                        f"{sorted(REMEDIATIONS)}")
    return spec
