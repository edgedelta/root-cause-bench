import hashlib

from tools.scenario_gen.degrade import apply_degradations

SPEC = {"degradations": [
    {"type": "drop_logs", "service": "svc-a", "after": "2026-07-20T09:30:00Z"},
    {"type": "clock_skew", "target": "metrics", "service": "svc-b", "offset_s": 90},
    {"type": "sample_traces", "rate": 0.5},
]}

LOGS = [
    {"timestamp": "2026-07-20T09:00:00Z", "service": "svc-a", "msg": "ok"},
    {"timestamp": "2026-07-20T09:31:00Z", "service": "svc-a", "msg": "gone"},
    {"timestamp": "2026-07-20T09:31:00Z", "service": "svc-b", "msg": "kept"},
]
METRICS = [
    {"timestamp": "2026-07-20T09:00:00Z", "service": "svc-b", "metric": "m", "value": 1},
    {"timestamp": "2026-07-20T09:00:00Z", "service": "svc-a", "metric": "m", "value": 1},
]
TRACES = [{"trace_id": f"{i:032x}", "span_id": "s0", "parent_id": None,
           "service": "svc-a", "name": "op", "start": "2026-07-20T09:00:00Z",
           "duration_ms": 5, "status": "OK"} for i in range(200)]


def test_drop_logs_removes_only_target_service_after_cutoff():
    logs, _, _ = apply_degradations(SPEC, list(LOGS), list(METRICS), list(TRACES))
    assert [r["msg"] for r in logs] == ["ok", "kept"]


def test_clock_skew_shifts_only_target():
    _, metrics, _ = apply_degradations(SPEC, list(LOGS), list(METRICS), list(TRACES))
    by_svc = {r["service"]: r["timestamp"] for r in metrics}
    assert by_svc["svc-b"] == "2026-07-20T09:01:30Z"
    assert by_svc["svc-a"] == "2026-07-20T09:00:00Z"


def test_sample_traces_deterministic_hash_rule():
    _, _, traces = apply_degradations(SPEC, list(LOGS), list(METRICS), list(TRACES))
    expect = [t for t in TRACES
              if int(hashlib.md5(t["trace_id"].encode()).hexdigest(), 16)
              % 10_000 < 5_000]
    assert traces == expect
    assert 0 < len(traces) < len(TRACES)


def test_no_degradations_is_identity():
    logs, metrics, traces = apply_degradations(
        {"degradations": []}, list(LOGS), list(METRICS), list(TRACES))
    assert (logs, metrics, traces) == (LOGS, METRICS, TRACES)
