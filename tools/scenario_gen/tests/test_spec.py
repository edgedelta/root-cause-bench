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
