import re
from pathlib import Path

from tools.scenario_gen.changes import build_changes
from tools.scenario_gen.spec import load_spec, parse_ts
from tools.scenario_gen.tests.test_spec import MINIMAL, write

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def spec(tmp_path):
    return load_spec(write(tmp_path, MINIMAL))


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
