# tools/scenario_gen/tests/test_telemetry.py
from tools.scenario_gen.spec import load_spec, parse_ts
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


# A ratio metric (baseline right at its natural ceiling of 1.0, with jitter
# wide enough that plain baseline*(1+jitter) overshoots past 1.0 on its own,
# no fault needed) -- reproducing this with MINIMAL's seed (7) confirms
# several of the 241 rows land above 1.0 pre-fix.
CLAMPED = MINIMAL.replace(
    '[[services.metrics]]\nname = "latency_p99_ms"\nbaseline = 120\n',
    '[[services.metrics]]\nname = "latency_p99_ms"\nbaseline = 120\n'
    '[[services.metrics]]\nname = "cache_hit_ratio"\nbaseline = 1.0\n'
    'jitter = 0.15\nclamp_min = 0.0\nclamp_max = 1.0\n',
)


def test_metric_clamp_max_bounds_jittered_ratio_metric(tmp_path):
    s = load_spec(write(tmp_path, CLAMPED))
    rows = build_metrics(s)
    ratio_vals = [r["value"] for r in rows if r["metric"] == "cache_hit_ratio"]
    assert ratio_vals
    assert all(v <= 1.0 for v in ratio_vals), ratio_vals
    assert all(v >= 0.0 for v in ratio_vals), ratio_vals


def test_metric_without_clamp_fields_is_unaffected(tmp_path):
    s = spec(tmp_path)
    m = s["services"][0]["metrics"][0]
    assert m["clamp_min"] is None and m["clamp_max"] is None


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
    # ramp reaches `to`, within default 5% fault jitter
    assert end_row and abs(end_row[0]["value"] - 900) < 0.1 * 900


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


def test_patterns_dedupes_repeated_fault_signature(tmp_path):
    # a precursor stage and an onset stage of the same signature (same msg,
    # same service; different windows/rates) must collapse to ONE pattern
    # entry whose count is the file-wide total across both faults.
    dup = FAULTY.replace(
        '''[[incident.log_faults]]
service = "svc-a"
msg = "query took 1450ms: timeout"
severity = "ERROR"
rate_per_min = 3
''',
        '''[[incident.log_faults]]
service = "svc-a"
msg = "query took 1450ms: timeout"
severity = "WARN"
rate_per_min = 1
start = "2026-07-20T06:00:00Z"
end = "2026-07-20T09:30:00Z"
[[incident.log_faults]]
service = "svc-a"
msg = "query took 1450ms: timeout"
severity = "ERROR"
rate_per_min = 3
''',
    )
    s = load_spec(write(tmp_path, dup))
    logs = build_logs(s)
    pats = build_patterns(s, logs)
    matches = [p for p in pats if p["signature"] == "query took <N>ms: timeout"
               and p["service"] == "svc-a"]
    assert len(matches) == 1
    total = sum(1 for r in logs if r["msg"] == "query took 1450ms: timeout"
                and r["service"] == "svc-a")
    assert matches[0]["count"] == total
    assert total == 300                    # 210 precursor rows + 90 onset rows


def test_in_patterns_false_suppresses_fault_from_patterns_not_logs(tmp_path):
    suppressed = FAULTY.replace(
        'msg = "query took 1450ms: timeout"',
        'msg = "query took 1450ms: timeout"\nin_patterns = false',
    )
    s = load_spec(write(tmp_path, suppressed))
    logs = build_logs(s)
    errs = [r for r in logs if r["severity_text"] == "ERROR"]
    assert len(errs) == 90                          # fault rows still land in logs
    pats = build_patterns(s, logs)
    assert not any(p["sentiment"] == "negative" for p in pats)  # but absent from patterns


def test_patterns_extra_passed_through_verbatim(tmp_path):
    extra = FAULTY.replace(
        "[incident]",
        '''[[patterns_extra]]
signature = "connection pool exhausted"
service = "svc-b"
count = 12
delta_vs_baseline = "+3"
sentiment = "negative"

[incident]''',
    )
    s = load_spec(write(tmp_path, extra))
    pats = build_patterns(s, build_logs(s))
    assert {"signature": "connection pool exhausted", "service": "svc-b",
            "count": 12, "delta_vs_baseline": "+3", "sentiment": "negative"} in pats


def test_patterns_ordered_negative_first_then_by_count_desc(tmp_path):
    extra = FAULTY.replace(
        "[incident]",
        '''[[patterns_extra]]
signature = "stale background negative"
service = "svc-b"
count = 5
delta_vs_baseline = "+1"
sentiment = "negative"

[incident]''',
    )
    s = load_spec(write(tmp_path, extra))
    pats = build_patterns(s, build_logs(s))
    neg = [p for p in pats if p["sentiment"] == "negative"]
    rest = [p for p in pats if p["sentiment"] != "negative"]
    assert pats == neg + rest
    assert [p["count"] for p in neg] == sorted((p["count"] for p in neg), reverse=True)
    assert [p["count"] for p in rest] == sorted((p["count"] for p in rest), reverse=True)
    # the fault (count 90) outranks the stale background negative (count 5)
    assert neg[0]["count"] == 90


def test_no_baseline_templates_yields_only_fault_logs(tmp_path):
    no_logs = FAULTY.replace(
        '''[[services.logs]]
msg = "request served"
severity = "INFO"
''', '')
    s = load_spec(write(tmp_path, no_logs))
    logs = build_logs(s)
    assert logs
    assert all(r["severity_text"] == "ERROR" for r in logs)
    assert all(r["msg"] == "query took 1450ms: timeout" for r in logs)


def test_all_zero_weight_log_templates_treated_as_no_templates(tmp_path):
    zero_weight = FAULTY.replace(
        '''[[services.logs]]
msg = "request served"
severity = "INFO"
''', '''[[services.logs]]
msg = "request served"
severity = "INFO"
weight = 0
''')
    s = load_spec(write(tmp_path, zero_weight))
    logs = build_logs(s)  # must not raise (rng.choices requires weight sum > 0)
    assert logs
    assert all(r["severity_text"] == "ERROR" for r in logs)
    assert all(r["msg"] == "query took 1450ms: timeout" for r in logs)


def test_trace_flow_end_bounds_spans(tmp_path):
    s = spec(tmp_path)
    mid = "2026-07-20T08:00:00Z"          # window is 06:00-10:00
    s["trace_flows"][0]["end"] = mid
    exemplar = {"trace_id": "y" * 32, "span_id": "e1", "parent_id": None,
                "service": "svc-a", "name": "GET /api/a",
                "start": "2026-07-20T09:45:00Z", "duration_ms": 10,
                "status": "OK"}
    s["incident"]["trace_exemplars"] = [exemplar]
    spans = build_traces(s)
    flow_spans, ex_spans = spans[:-1], spans[-1:]
    assert flow_spans
    assert all(sp["start"] < mid for sp in flow_spans)
    assert ex_spans == [exemplar]        # exemplar spans unaffected by flow end


RATIO = FAULTY.replace(
    '''[[services.metrics]]
name = "latency_p99_ms"
baseline = 120''',
    '''[[services.metrics]]
name = "latency_p99_ms"
baseline = 120
[[services.metrics]]
name = "cache_hit_ratio"
baseline = 0.97
jitter = 0.01''')


def test_ratio_metric_precision_not_flattened(tmp_path):
    s = load_spec(write(tmp_path, RATIO))
    rows = build_metrics(s)
    vals = [r["value"] for r in rows if r["metric"] == "cache_hit_ratio"]
    assert len(vals) > 1
    assert len(set(vals)) > 1                    # jitter must survive rounding
    assert all(0.955 <= v <= 0.985 for v in vals)
    assert not all(v == 1.0 for v in vals)


SPIKE = FAULTY.replace('curve = "ramp"', 'curve = "spike"').replace(
    '''[[services.metrics]]
name = "latency_p99_ms"
baseline = 120''',
    '''[[services.metrics]]
name = "latency_p99_ms"
baseline = 120
jitter = 0.01''')

JITTERY = FAULTY.replace(
    '''[[services.metrics]]
name = "latency_p99_ms"
baseline = 120''',
    '''[[services.metrics]]
name = "latency_p99_ms"
baseline = 120
jitter = 0.1''')


def test_spike_curve_peaks_near_mid_and_returns_to_baseline(tmp_path):
    s = load_spec(write(tmp_path, SPIKE))
    rows = build_metrics(s)
    svc = [r for r in rows if r["metric"] == "latency_p99_ms"]
    # onset (fault start) 09:30, fault end defaults to window end 10:00
    end_row = [r for r in svc if r["timestamp"] == "2026-07-20T10:00:00Z"]
    assert end_row and abs(end_row[0]["value"] - 120) < 10   # back near baseline
    mid_row = [r for r in svc if r["timestamp"] == "2026-07-20T09:45:00Z"]
    assert mid_row and abs(mid_row[0]["value"] - 900) < 30   # peaks near `to` at mid
    after_onset = [r["value"] for r in svc
                   if r["timestamp"] >= "2026-07-20T09:30:00Z"]
    assert max(after_onset) <= 900 * 1.05                    # never overshoots `to`


def test_fault_values_deviate_from_exact_interpolation_with_jitter(tmp_path):
    s = load_spec(write(tmp_path, JITTERY))
    rows = build_metrics(s)
    svc = [r for r in rows if r["metric"] == "latency_p99_ms"]
    fs, fe = parse_ts("2026-07-20T09:30:00Z"), parse_ts("2026-07-20T10:00:00Z")
    deltas = set()
    for r in svc:
        t = parse_ts(r["timestamp"])
        if t < fs:
            continue
        frac = min(1.0, (t - fs) / (fe - fs)) if fe > fs else 1.0
        ideal = 120 + (900 - 120) * frac
        deltas.add(round(r["value"] - ideal, 3))
    assert len(deltas) >= 2                      # not a single exact interpolation
    assert any(d != 0 for d in deltas)


def test_metrics_deterministic_with_fault_jitter(tmp_path):
    s1 = load_spec(write(tmp_path, JITTERY))
    rows_a = build_metrics(s1)
    s2 = load_spec(write(tmp_path, JITTERY))
    rows_b = build_metrics(s2)
    assert rows_a == rows_b
