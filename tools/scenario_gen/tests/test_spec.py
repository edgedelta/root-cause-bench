# tools/scenario_gen/tests/test_spec.py
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.scenario_gen.spec import SpecError, fmt_ts, load_spec, parse_ts

MINIMAL = '''
name = "demo-scenario"
family = "guilty-decoy"
seed = 7

[window]
start = "2026-07-20T06:00:00Z"
end   = "2026-07-20T10:00:00Z"

[alert]
service = "svc-a"
metric = "latency_p99_ms"
threshold = 500
fired_at = "2026-07-20T09:50:00Z"
summary = "p99 breach"
detail = "svc-a latency_p99_ms > 500"

[[services]]
name = "svc-a"
[[services.logs]]
msg = "request served"
severity = "INFO"
[[services.metrics]]
name = "latency_p99_ms"
baseline = 120

[incident]
onset = "2026-07-20T09:30:00Z"
first_failing_service = "svc-a"

[[commits.authored]]
id = "culprit"
message = "refactor: simplify handler"
author = "dev.one"
timestamp = "2026-07-20T07:00:00Z"
files = ["services/a/handler.go"]
diff = "--- a/services/a/handler.go\\n+++ b/services/a/handler.go\\n@@ -1 +1 @@\\n-old\\n+new\\n"

[[deploys]]
service = "svc-a"
commit = "culprit"
timestamp = "2026-07-20T09:20:00Z"

[ground_truth]
culprit_id = "culprit"
blast_radius = []
remediation = "rollback"
notes = "test scenario"
'''


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "scenario.toml"
    p.write_text(text)
    return p


def test_parse_and_fmt_ts_roundtrip():
    ts = parse_ts("2026-07-20T06:00:00Z")
    assert ts == datetime(2026, 7, 20, 6, tzinfo=timezone.utc)
    assert fmt_ts(ts) == "2026-07-20T06:00:00Z"


def test_load_minimal_spec_applies_defaults(tmp_path):
    spec = load_spec(write(tmp_path, MINIMAL))
    assert spec["difficulty"] == "adversarial"
    assert spec["window"]["metric_step_s"] == 60
    assert spec["window"]["log_rps"] == 0.05
    assert spec["commits"]["innocent_count"] == 24
    assert spec["services"][0]["logs"][0]["weight"] == 1
    assert spec["services"][0]["metrics"][0]["jitter"] == 0.05
    assert spec["ground_truth"]["decoy_ids"] == []
    assert spec["overrides"]["keep"] == []
    assert spec["flags"] == []
    assert spec["degradations"] == []
    assert spec["trace_flows"] == []
    assert "adversarial" in spec["tags"] and "guilty-decoy" in spec["tags"]


def test_unknown_deploy_commit_id_rejected(tmp_path):
    bad = MINIMAL.replace('commit = "culprit"', 'commit = "nope"')
    with pytest.raises(SpecError, match="deploy references unknown commit id 'nope'"):
        load_spec(write(tmp_path, bad))


def test_unknown_culprit_id_rejected(tmp_path):
    bad = MINIMAL.replace('culprit_id = "culprit"', 'culprit_id = "ghost"')
    with pytest.raises(SpecError, match="culprit_id 'ghost'"):
        load_spec(write(tmp_path, bad))


def test_culprit_none_allowed(tmp_path):
    ok = MINIMAL.replace('culprit_id = "culprit"', 'culprit_id = "none"')
    assert load_spec(write(tmp_path, ok))["ground_truth"]["culprit_id"] == "none"


def test_onset_after_window_end_rejected(tmp_path):
    bad = MINIMAL.replace('onset = "2026-07-20T09:30:00Z"',
                          'onset = "2026-07-20T11:30:00Z"')
    with pytest.raises(SpecError, match="onset"):
        load_spec(write(tmp_path, bad))


def test_bad_family_rejected(tmp_path):
    bad = MINIMAL.replace('family = "guilty-decoy"', 'family = "whatever"')
    with pytest.raises(SpecError, match="family"):
        load_spec(write(tmp_path, bad))


def test_zero_innocent_count_rejected(tmp_path):
    # A bare `innocent_count = 0` inserted right before `[[commits.authored]]`
    # would parse under the still-open `[incident]` table, not `[commits]`
    # (verified against tomllib) -- so an explicit `[commits]` header is
    # required to land the key in the right table.
    bad = MINIMAL.replace("[[commits.authored]]",
                          "[commits]\ninnocent_count = 0\n\n[[commits.authored]]", 1)
    with pytest.raises(SpecError, match="innocent_count must be >= 1"):
        load_spec(write(tmp_path, bad))


def test_authored_timestamp_at_window_end_rejected(tmp_path):
    bad = MINIMAL.replace('timestamp = "2026-07-20T07:00:00Z"',
                          'timestamp = "2026-07-20T10:00:00Z"')
    with pytest.raises(SpecError, match="strictly before window.end"):
        load_spec(write(tmp_path, bad))


def test_deploys_auto_defaults(tmp_path):
    spec = load_spec(write(tmp_path, MINIMAL))
    assert spec["deploys_auto"]["count"] == 0
    assert spec["deploys_auto"]["services"] == ["svc-a"]
    assert spec["deploys_auto"]["pre_onset_min"] == 0


def test_deploys_auto_negative_count_rejected(tmp_path):
    bad = MINIMAL.replace(
        "[ground_truth]",
        "[deploys_auto]\ncount = -1\n\n[ground_truth]",
    )
    with pytest.raises(SpecError, match="count"):
        load_spec(write(tmp_path, bad))


def test_deploys_auto_unknown_service_rejected(tmp_path):
    bad = MINIMAL.replace(
        "[ground_truth]",
        '[deploys_auto]\ncount = 2\nservices = ["svc-ghost"]\n\n[ground_truth]',
    )
    with pytest.raises(SpecError, match="deploys_auto"):
        load_spec(write(tmp_path, bad))


def test_patterns_extra_missing_key_rejected(tmp_path):
    bad = MINIMAL.replace(
        "[incident]",
        '[[patterns_extra]]\nsignature = "x"\nservice = "svc-a"\ncount = 1\n'
        'delta_vs_baseline = "+1"\n\n[incident]',
    )
    with pytest.raises(SpecError, match="patterns_extra.*sentiment"):
        load_spec(write(tmp_path, bad))


def test_deploys_auto_pre_onset_min_exceeds_count_rejected(tmp_path):
    bad = MINIMAL.replace(
        "[ground_truth]",
        "[deploys_auto]\ncount = 2\npre_onset_min = 3\n\n[ground_truth]",
    )
    with pytest.raises(SpecError, match="pre_onset_min"):
        load_spec(write(tmp_path, bad))


def test_alert_missing_field_rejected(tmp_path):
    bad = MINIMAL.replace('detail = "svc-a latency_p99_ms > 500"\n', "")
    with pytest.raises(SpecError, match="alert.*detail"):
        load_spec(write(tmp_path, bad))


def test_metric_fault_missing_service_rejected(tmp_path):
    bad = MINIMAL.replace(
        'first_failing_service = "svc-a"',
        'first_failing_service = "svc-a"\n'
        '[[incident.metric_faults]]\nmetric = "latency_p99_ms"\nto = 900\n',
    )
    with pytest.raises(SpecError, match="metric_faults.*0.*service"):
        load_spec(write(tmp_path, bad))


def test_metric_fault_missing_metric_rejected(tmp_path):
    bad = MINIMAL.replace(
        'first_failing_service = "svc-a"',
        'first_failing_service = "svc-a"\n'
        '[[incident.metric_faults]]\nservice = "svc-a"\nto = 900\n',
    )
    with pytest.raises(SpecError, match="metric_faults.*0.*metric"):
        load_spec(write(tmp_path, bad))


def test_metric_fault_missing_to_rejected(tmp_path):
    bad = MINIMAL.replace(
        'first_failing_service = "svc-a"',
        'first_failing_service = "svc-a"\n'
        '[[incident.metric_faults]]\nservice = "svc-a"\nmetric = "latency_p99_ms"\n',
    )
    with pytest.raises(SpecError, match="metric_faults.*0.*to"):
        load_spec(write(tmp_path, bad))


def test_log_fault_missing_service_rejected(tmp_path):
    bad = MINIMAL.replace(
        'first_failing_service = "svc-a"',
        'first_failing_service = "svc-a"\n'
        '[[incident.log_faults]]\nmsg = "boom"\n',
    )
    with pytest.raises(SpecError, match="log_faults.*0.*service"):
        load_spec(write(tmp_path, bad))


def test_log_fault_missing_msg_rejected(tmp_path):
    bad = MINIMAL.replace(
        'first_failing_service = "svc-a"',
        'first_failing_service = "svc-a"\n'
        '[[incident.log_faults]]\nservice = "svc-a"\n',
    )
    with pytest.raises(SpecError, match="log_faults.*0.*msg"):
        load_spec(write(tmp_path, bad))


def test_log_fault_zero_rate_per_min_rejected(tmp_path):
    bad = MINIMAL.replace(
        'first_failing_service = "svc-a"',
        'first_failing_service = "svc-a"\n'
        '[[incident.log_faults]]\nservice = "svc-a"\nmsg = "boom"\n'
        'rate_per_min = 0\n',
    )
    with pytest.raises(SpecError, match="rate_per_min"):
        load_spec(write(tmp_path, bad))


def test_log_fault_negative_rate_per_min_rejected(tmp_path):
    bad = MINIMAL.replace(
        'first_failing_service = "svc-a"',
        'first_failing_service = "svc-a"\n'
        '[[incident.log_faults]]\nservice = "svc-a"\nmsg = "boom"\n'
        'rate_per_min = -2\n',
    )
    with pytest.raises(SpecError, match="rate_per_min"):
        load_spec(write(tmp_path, bad))


def test_log_fault_string_rate_per_min_rejected(tmp_path):
    bad = MINIMAL.replace(
        'first_failing_service = "svc-a"',
        'first_failing_service = "svc-a"\n'
        '[[incident.log_faults]]\nservice = "svc-a"\nmsg = "boom"\n'
        'rate_per_min = "fast"\n',
    )
    with pytest.raises(SpecError, match="log_faults.*0.*rate_per_min.*positive number"):
        load_spec(write(tmp_path, bad))


def test_log_fault_bool_rate_per_min_rejected(tmp_path):
    bad = MINIMAL.replace(
        'first_failing_service = "svc-a"',
        'first_failing_service = "svc-a"\n'
        '[[incident.log_faults]]\nservice = "svc-a"\nmsg = "boom"\n'
        'rate_per_min = true\n',
    )
    with pytest.raises(SpecError, match="log_faults.*0.*rate_per_min.*positive number"):
        load_spec(write(tmp_path, bad))


def test_duplicate_metric_fault_service_metric_pair_rejected(tmp_path):
    bad = MINIMAL.replace(
        'first_failing_service = "svc-a"',
        'first_failing_service = "svc-a"\n'
        '[[incident.metric_faults]]\nservice = "svc-a"\nmetric = "latency_p99_ms"\n'
        'to = 900\n'
        '[[incident.metric_faults]]\nservice = "svc-a"\nmetric = "latency_p99_ms"\n'
        'to = 950\n',
    )
    with pytest.raises(SpecError, match="duplicate.*svc-a.*latency_p99_ms"):
        load_spec(write(tmp_path, bad))


def test_drop_logs_degradation_requires_service_and_after(tmp_path):
    bad = MINIMAL.replace(
        "[ground_truth]",
        '[[degradations]]\ntype = "drop_logs"\n\n[ground_truth]',
    )
    with pytest.raises(SpecError, match="drop_logs.*service"):
        load_spec(write(tmp_path, bad))


def test_drop_logs_degradation_requires_valid_after_timestamp(tmp_path):
    bad = MINIMAL.replace(
        "[ground_truth]",
        '[[degradations]]\ntype = "drop_logs"\nservice = "svc-a"\n'
        'after = "not-a-timestamp"\n\n[ground_truth]',
    )
    with pytest.raises(SpecError, match="bad timestamp"):
        load_spec(write(tmp_path, bad))


def test_clock_skew_degradation_requires_valid_target(tmp_path):
    bad = MINIMAL.replace(
        "[ground_truth]",
        '[[degradations]]\ntype = "clock_skew"\ntarget = "nope"\noffset_s = 5\n'
        '\n[ground_truth]',
    )
    with pytest.raises(SpecError, match="clock_skew.*target"):
        load_spec(write(tmp_path, bad))


def test_clock_skew_degradation_requires_numeric_offset(tmp_path):
    bad = MINIMAL.replace(
        "[ground_truth]",
        '[[degradations]]\ntype = "clock_skew"\ntarget = "logs"\n'
        'offset_s = "soon"\n\n[ground_truth]',
    )
    with pytest.raises(SpecError, match="clock_skew.*offset_s"):
        load_spec(write(tmp_path, bad))


def test_sample_traces_degradation_requires_rate_in_range(tmp_path):
    bad = MINIMAL.replace(
        "[ground_truth]",
        '[[degradations]]\ntype = "sample_traces"\nrate = 0\n\n[ground_truth]',
    )
    with pytest.raises(SpecError, match="sample_traces.*rate"):
        load_spec(write(tmp_path, bad))


def test_sample_traces_degradation_rejects_rate_above_one(tmp_path):
    bad = MINIMAL.replace(
        "[ground_truth]",
        '[[degradations]]\ntype = "sample_traces"\nrate = 1.5\n\n[ground_truth]',
    )
    with pytest.raises(SpecError, match="sample_traces.*rate"):
        load_spec(write(tmp_path, bad))


def test_hand_authored_deploy_timestamp_before_window_start_rejected(tmp_path):
    bad = MINIMAL.replace(
        'timestamp = "2026-07-20T09:20:00Z"\n\n[ground_truth]',
        'timestamp = "2026-07-20T05:00:00Z"\n\n[ground_truth]',
    )
    with pytest.raises(SpecError, match="deploys?.*window"):
        load_spec(write(tmp_path, bad))


def test_hand_authored_deploy_timestamp_after_window_end_rejected(tmp_path):
    bad = MINIMAL.replace(
        'timestamp = "2026-07-20T09:20:00Z"\n\n[ground_truth]',
        'timestamp = "2026-07-20T11:00:00Z"\n\n[ground_truth]',
    )
    with pytest.raises(SpecError, match="deploys?.*window"):
        load_spec(write(tmp_path, bad))
