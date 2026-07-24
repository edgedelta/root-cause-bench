import random
import re

import pytest

from tools.scenario_gen.changes import INNOCENT_POOL, _redraw_pre_onset, build_changes
from tools.scenario_gen.spec import SpecError, load_spec, parse_ts
from tools.scenario_gen.tests.test_spec import MINIMAL, write

SHA_RE = re.compile(r"^[0-9a-f]{40}$")

WITH_AUTO = MINIMAL.replace(
    "[ground_truth]",
    "[deploys_auto]\ncount = 12\npre_onset_min = 4\n\n[ground_truth]",
)

# Onset moved early in the window so most randomly-drawn deploy timestamps
# land after it, forcing the pre_onset_min shortfall/redraw path to fire for
# every one of the 6 auto deploys.
SHORTFALL = MINIMAL.replace(
    'onset = "2026-07-20T09:30:00Z"',
    'onset = "2026-07-20T06:45:00Z"',
).replace(
    "[ground_truth]",
    "[deploys_auto]\ncount = 6\npre_onset_min = 6\n\n[ground_truth]",
)

# A second service so round-robin cycling is actually exercised.
MULTI_SERVICE = MINIMAL.replace(
    "[incident]",
    '[[services]]\n'
    'name = "svc-b"\n'
    '[[services.logs]]\n'
    'msg = "request served"\n'
    'severity = "INFO"\n'
    '[[services.metrics]]\n'
    'name = "latency_p99_ms"\n'
    'baseline = 100\n'
    '\n[incident]',
    1,
).replace(
    "[ground_truth]",
    "[deploys_auto]\ncount = 6\n\n[ground_truth]",
)


def spec(tmp_path):
    return load_spec(write(tmp_path, MINIMAL))


def spec_with_auto(tmp_path):
    return load_spec(write(tmp_path, WITH_AUTO))


def spec_shortfall(tmp_path):
    return load_spec(write(tmp_path, SHORTFALL))


def spec_multi_service(tmp_path):
    return load_spec(write(tmp_path, MULTI_SERVICE))


def test_deterministic_and_schema(tmp_path):
    s = spec(tmp_path)
    commits1, deploys1, flags1, ids1 = build_changes(s)
    commits2, _, _, ids2 = build_changes(spec(tmp_path))
    assert commits1 == commits2 and ids1 == ids2
    assert len(commits1) == 1 + s["commits"]["innocent_count"]
    for c in commits1:
        assert SHA_RE.match(c["sha"])
        assert set(c) == {"sha", "author", "timestamp", "message",
                          "files_changed", "diff"}
    assert len({c["sha"] for c in commits1}) == len(commits1)


def test_authored_commit_carries_diff_and_deploy_resolves(tmp_path):
    commits, deploys, _, ids = build_changes(spec(tmp_path))
    culprit = next(c for c in commits if c["sha"] == ids["culprit"])
    assert culprit["diff"].startswith("--- a/")
    assert culprit["message"] == "refactor: simplify handler"
    assert deploys[0]["commit_sha"] == ids["culprit"]
    assert deploys[0]["service"] == "svc-a"
    assert deploys[0]["version"].startswith("v2026.07.20-")


def test_newest_commit_is_innocent(tmp_path):
    commits, _, _, ids = build_changes(spec(tmp_path))
    newest = max(commits, key=lambda c: c["timestamp"])
    assert newest["sha"] not in ids.values()


def test_commits_sorted_by_timestamp(tmp_path):
    commits, _, _, _ = build_changes(spec(tmp_path))
    ts = [c["timestamp"] for c in commits]
    assert ts == sorted(ts)


def test_deploys_auto_absent_yields_authored_only(tmp_path):
    _, deploys, _, _ = build_changes(spec(tmp_path))
    assert len(deploys) == 1


def test_deploys_auto_deterministic(tmp_path):
    s = spec_with_auto(tmp_path)
    _, deploys1, _, _ = build_changes(s)
    _, deploys2, _, _ = build_changes(spec_with_auto(tmp_path))
    assert deploys1 == deploys2


def test_deploys_auto_count(tmp_path):
    s = spec_with_auto(tmp_path)
    _, deploys, _, _ = build_changes(s)
    assert len(deploys) == 1 + s["deploys_auto"]["count"]


def test_deploys_auto_commits_are_innocent_and_precede_deploy(tmp_path):
    s = spec_with_auto(tmp_path)
    commits, deploys, _, ids = build_changes(s)
    innocent_shas = {c["sha"] for c in commits} - set(ids.values())
    sha_to_ts = {c["sha"]: c["timestamp"] for c in commits}
    # skip the single hand-authored deploy (references the culprit commit).
    auto_deploys = [d for d in deploys if d["commit_sha"] != ids["culprit"]]
    assert len(auto_deploys) == s["deploys_auto"]["count"]
    for d in auto_deploys:
        assert d["commit_sha"] in innocent_shas
        assert parse_ts(sha_to_ts[d["commit_sha"]]) < parse_ts(d["timestamp"])


def test_deploys_auto_respects_pre_onset_min(tmp_path):
    s = spec_with_auto(tmp_path)
    _, deploys, _, _ = build_changes(s)
    onset = parse_ts(s["incident"]["onset"])
    before = [d for d in deploys if parse_ts(d["timestamp"]) < onset]
    assert len(before) >= s["deploys_auto"]["pre_onset_min"]


def test_deploys_auto_sorted_by_timestamp(tmp_path):
    s = spec_with_auto(tmp_path)
    _, deploys, _, _ = build_changes(s)
    ts = [d["timestamp"] for d in deploys]
    assert ts == sorted(ts)


def test_deploys_auto_shortfall_redraw_all_land_pre_onset(tmp_path):
    # pre_onset_min == count, with onset early in the window, forces the
    # shortfall/redraw path for every auto-generated deploy.
    s = spec_shortfall(tmp_path)
    commits, deploys, _, ids = build_changes(s)
    onset = parse_ts(s["incident"]["onset"])
    sha_to_ts = {c["sha"]: c["timestamp"] for c in commits}
    auto_deploys = [d for d in deploys if d["commit_sha"] != ids["culprit"]]
    assert len(auto_deploys) == s["deploys_auto"]["count"] == 6
    for d in auto_deploys:
        assert parse_ts(d["timestamp"]) < onset
        assert parse_ts(sha_to_ts[d["commit_sha"]]) < parse_ts(d["timestamp"])


def test_redraw_pre_onset_raises_when_unsatisfiable():
    # Direct unit test of the new guard: no innocent commit is authored
    # before onset, so pre_onset_min can never be satisfied.
    onset = parse_ts("2026-07-20T06:45:00Z")
    innocent_commits = [
        {"sha": "a" * 40, "timestamp": "2026-07-20T07:00:00Z"},
        {"sha": "b" * 40, "timestamp": "2026-07-20T08:00:00Z"},
    ]
    with pytest.raises(SpecError, match="pre_onset_min unsatisfiable"):
        _redraw_pre_onset(random.Random(1), onset, innocent_commits)


def test_innocent_pool_entries_have_realistic_diffs():
    # Every innocent-pool entry must carry a small, plausible diff (no more
    # `None`), so the culprit isn't the only commit with a mechanism-bearing
    # change to point at.
    assert len(INNOCENT_POOL) >= 24
    seen_messages = set()
    for msg, files, diff in INNOCENT_POOL:
        assert isinstance(diff, str) and diff.strip(), msg
        assert files
        assert msg not in seen_messages, f"duplicate innocent message {msg!r}"
        seen_messages.add(msg)


def test_innocent_commits_never_have_null_diff(tmp_path):
    commits, _, _, ids = build_changes(spec(tmp_path))
    innocent = [c for c in commits if c["sha"] not in ids.values()]
    assert innocent
    for c in innocent:
        assert isinstance(c["diff"], str) and c["diff"]


def test_deploys_auto_round_robin_cycles_services(tmp_path):
    s = spec_multi_service(tmp_path)
    _, deploys, _, ids = build_changes(s)
    auto_deploys = [d for d in deploys if d["commit_sha"] != ids["culprit"]]
    assert len(auto_deploys) == 6
    counts = {}
    for d in auto_deploys:
        counts[d["service"]] = counts.get(d["service"], 0) + 1
    assert counts == {"svc-a": 3, "svc-b": 3}
