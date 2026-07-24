# tools/scenario_gen/tests/test_telemetry.py
from tools.scenario_gen.spec import load_spec
from tools.scenario_gen.telemetry import (build_logs, build_metrics,
                                          build_patterns, build_traces)
from tools.scenario_gen.tests.test_spec import MINIMAL, write

FAULTY = MINIMAL.replace(
    "[incident]",
    '''[[trace_flows]]
name = "GET /api/a"
per_hour = 2
[[trace_flows.spans]]
service = "svc-a"
name = "GET /api/a"
duration_ms = 40

[incident]''',
).replace(
    'first_failing_service = "svc-a"',
    '''first_failing_service = "svc-a"
[[incident.metric_faults]]
service = "svc-a"
metric = "latency_p99_ms"
curve = "ramp"
to = 900
[[incident.log_faults]]
service = "svc-a"
msg = "query took 1450ms: timeout"
severity = "ERROR"
rate_per_min = 3
''',
)


def spec(tmp_path):
    return load_spec(write(tmp_path, FAULTY))


def test_logs_sorted_deterministic_with_fault_rows(tmp_path):
    s = spec(tmp_path)
    logs = build_logs(s)
    assert logs == build_logs(spec(tmp_path))
    ts = [r["timestamp"] for r in logs]
    assert ts == sorted(ts)
    errs = [r for r in logs if r["severity_text"] == "ERROR"]
    # 3/min from 09:30 to 10:00 = 90 rows
    assert len(errs) == 90
    assert all(r["timestamp"] >= "2026-07-20T09:30:00Z" for r in errs)
    assert all(set(r) >= {"timestamp", "service", "severity_text", "msg",
                          "trace_id"} for r in logs)


def test_metrics_baseline_then_ramp(tmp_path):
    rows = build_metrics(spec(tmp_path))
    svc = [r for r in rows if r["metric"] == "latency_p99_ms"]
    before = [r["value"] for r in svc if r["timestamp"] < "2026-07-20T09:30:00Z"]
    assert all(100 <= v <= 140 for v in before)          # baseline 120 ± 5% jitter
    end_row = [r for r in svc if r["timestamp"] == "2026-07-20T10:00:00Z"]
    assert end_row and abs(end_row[0]["value"] - 900) < 1  # ramp reaches `to`


def test_traces_from_flows_plus_exemplars(tmp_path):
    s = spec(tmp_path)
    spans = build_traces(s)
    assert len(spans) == 8                                # 2/hour x 4h window
    assert all(len(sp["trace_id"]) == 32 for sp in spans)
    s["incident"]["trace_exemplars"] = [{"trace_id": "x" * 32, "span_id": "a1",
        "parent_id": None, "service": "svc-a", "name": "GET /api/a",
        "start": "2026-07-20T09:45:00Z", "duration_ms": 1450,
        "status": "ERROR", "error": "timeout"}]
    assert build_traces(s)[-1]["duration_ms"] == 1450


def test_patterns_fault_signature_numbers_collapsed(tmp_path):
    s = spec(tmp_path)
    pats = build_patterns(s, build_logs(s))
    neg = [p for p in pats if p["sentiment"] == "negative"]
    assert len(neg) == 1
    assert neg[0]["signature"] == "query took <N>ms: timeout"
    assert neg[0]["count"] == 90 and neg[0]["delta_vs_baseline"] == "+90"
    assert any(p["sentiment"] == "neutral" for p in pats)
