import ast
import json
import re
from pathlib import Path

import pytest

from tools.scenario_gen.changes import build_changes
from tools.scenario_gen.emit import _check_consistency, emit_scenario
from tools.scenario_gen.spec import SpecError, load_spec
from tools.scenario_gen.tests.test_spec import MINIMAL

# MINIMAL lacks a non-culprit deploy near fired_at. The decoy commit/deploy is
# pre-onset (09:05 authored, 09:25 deployed -- before onset 09:30) so it can't
# be dismissed on timing alone; "late-innocent" (authored 09:12, deployed
# 09:42) supplies the non-culprit deploy within 15min of fired_at (09:50) that
# the decoy-position consistency check requires.
FULL = MINIMAL.replace(
    "[ground_truth]",
    '''[[commits.authored]]
id = "decoy"
message = "chore: adjust css spacing on checkout page"
author = "sofia.rossi"
timestamp = "2026-07-20T09:05:00Z"
files = ["web/styles/checkout.css"]
diff = "--- a/web/styles/checkout.css\\n+++ b/web/styles/checkout.css\\n@@ -3 +3 @@\\n-margin: 4px\\n+margin: 6px\\n"

[[commits.authored]]
id = "late-innocent"
message = "style: tweak footer spacing"
author = "marco.silva"
timestamp = "2026-07-20T09:12:00Z"
files = ["web/styles/footer.css"]
diff = "--- a/web/styles/footer.css\\n+++ b/web/styles/footer.css\\n@@ -8 +8 @@\\n-padding: 8px\\n+padding: 10px\\n"

[[deploys]]
service = "svc-a"
commit = "decoy"
timestamp = "2026-07-20T09:25:00Z"

[[deploys]]
service = "svc-a"
commit = "late-innocent"
timestamp = "2026-07-20T09:42:00Z"

[ground_truth]''',
).replace('decoy_ids = []', '').replace(
    'notes = "test scenario"',
    'decoy_ids = ["decoy"]\nnotes = "test scenario"')


@pytest.fixture()
def scenario_dir(tmp_path):
    d = tmp_path / "datasets" / "rootcausebench" / "demo-scenario"
    d.mkdir(parents=True)
    (d / "scenario.toml").write_text(FULL)
    return d


def test_emit_writes_complete_scenario(scenario_dir):
    out = emit_scenario(scenario_dir / "scenario.toml")
    assert out == scenario_dir
    for rel in ("task.toml", "instruction.md", "environment/Dockerfile",
                "environment/data/alert.json", "environment/data/logs.ndjson",
                "environment/data/metrics.csv", "environment/data/traces.json",
                "environment/data/patterns.json",
                "environment/data/context/commits.json",
                "environment/data/context/deploys.json",
                "environment/data/context/flags.json",
                "solution/solve.sh", "tests/test.sh", "tests/test_outputs.py",
                "tests/ground_truth.json"):
        assert (scenario_dir / rel).exists(), rel

    gt = json.loads((scenario_dir / "tests/ground_truth.json").read_text())
    commits = json.loads(
        (scenario_dir / "environment/data/context/commits.json").read_text())
    shas = {c["sha"] for c in commits}
    assert gt["scenario"] == "demo-scenario"
    assert gt["root_cause_commit"] in shas
    assert set(gt["decoy_deploy_commits"]) <= shas
    assert 'difficulty = "adversarial"' in (scenario_dir / "task.toml").read_text()
    solve = (scenario_dir / "solution/solve.sh").read_text()
    assert gt["root_cause_commit"] in solve


def test_emit_respects_overrides_keep(scenario_dir):
    spec_path = scenario_dir / "scenario.toml"
    spec_path.write_text(FULL.replace(
        "[ground_truth]",
        '[overrides]\nkeep = ["environment/data/patterns.json"]\n\n[ground_truth]',
        1))
    pats = scenario_dir / "environment/data/patterns.json"
    pats.parent.mkdir(parents=True)
    pats.write_text('[{"signature": "handwritten"}]')
    emit_scenario(spec_path)
    assert json.loads(pats.read_text()) == [{"signature": "handwritten"}]


def test_culprit_deploy_after_onset_rejected(scenario_dir):
    bad = FULL.replace('timestamp = "2026-07-20T09:20:00Z"',
                       'timestamp = "2026-07-20T09:44:00Z"')
    (scenario_dir / "scenario.toml").write_text(bad)
    with pytest.raises(SpecError, match="culprit deploy .* after onset"):
        emit_scenario(scenario_dir / "scenario.toml")


def test_no_pre_onset_decoy_rejected(scenario_dir):
    # Push the decoy's only deploy to after onset (09:30) -- it becomes
    # dismissible on timing alone, which the new invariant forbids.
    bad = FULL.replace(
        '''[[deploys]]
service = "svc-a"
commit = "decoy"
timestamp = "2026-07-20T09:25:00Z"''',
        '''[[deploys]]
service = "svc-a"
commit = "decoy"
timestamp = "2026-07-20T09:44:00Z"''')
    (scenario_dir / "scenario.toml").write_text(bad)
    with pytest.raises(SpecError, match="no decoy deploy before onset"):
        emit_scenario(scenario_dir / "scenario.toml")


def test_deploy_not_strictly_after_commit_rejected(scenario_dir):
    # Regression test for the sub-second commit==deploy collapse invariant:
    # _check_consistency must reject any deploy whose commit timestamp is
    # not strictly before the deploy's own timestamp.
    spec = load_spec(scenario_dir / "scenario.toml")
    commits, deploys, _, id_to_sha = build_changes(spec)
    culprit_sha = id_to_sha[spec["ground_truth"]["culprit_id"]]
    culprit_ts = next(c["timestamp"] for c in commits if c["sha"] == culprit_sha)
    bad_deploys = [dict(d) for d in deploys]
    for d in bad_deploys:
        if d["commit_sha"] == culprit_sha:
            d["timestamp"] = culprit_ts
    with pytest.raises(SpecError, match="not strictly after its commit"):
        _check_consistency(spec, commits, bad_deploys, id_to_sha)


def test_deploy_outside_window_rejected(scenario_dir):
    spec = load_spec(scenario_dir / "scenario.toml")
    commits, deploys, _, id_to_sha = build_changes(spec)
    bad_deploys = [dict(d) for d in deploys]
    bad_deploys[0] = dict(bad_deploys[0])
    bad_deploys[0]["timestamp"] = "2026-07-20T11:00:00Z"  # window.end is 10:00
    with pytest.raises(SpecError, match="outside window"):
        _check_consistency(spec, commits, bad_deploys, id_to_sha)


def test_undeployed_culprit_rejected(scenario_dir):
    spec = load_spec(scenario_dir / "scenario.toml")
    commits, deploys, _, id_to_sha = build_changes(spec)
    culprit_sha = id_to_sha[spec["ground_truth"]["culprit_id"]]
    stripped_deploys = [d for d in deploys if d["commit_sha"] != culprit_sha]
    with pytest.raises(SpecError, match="never deployed"):
        _check_consistency(spec, commits, stripped_deploys, id_to_sha)


def test_sha_resolution_recheck(scenario_dir):
    spec = load_spec(scenario_dir / "scenario.toml")
    commits, deploys, flags, id_to_sha = build_changes(spec)

    culprit_sha = id_to_sha[spec["ground_truth"]["culprit_id"]]
    stripped_commits = [c for c in commits if c["sha"] != culprit_sha]

    with pytest.raises(SpecError, match="not in commits.json|does not resolve"):
        _check_consistency(spec, stripped_commits, deploys, id_to_sha)


DEGRADED = FULL.replace(
    "[ground_truth]",
    '''[[degradations]]
type = "drop_logs"
service = "svc-a"
after = "2026-07-20T09:30:00Z"

[ground_truth]''')


def test_patterns_reflect_degraded_logs(scenario_dir):
    spec_path = scenario_dir / "scenario.toml"
    spec_path.write_text(DEGRADED)
    emit_scenario(spec_path)
    logs = [json.loads(l) for l in
            (scenario_dir / "environment/data/logs.ndjson").read_text().splitlines()
            if l]
    patterns = json.loads(
        (scenario_dir / "environment/data/patterns.json").read_text())

    # the degradation must actually have removed rows for this test to mean anything
    assert not any(r["service"] == "svc-a" and r["timestamp"] >= "2026-07-20T09:30:00Z"
                   for r in logs)

    for p in patterns:
        actual = sum(1 for r in logs
                     if r["service"] == p["service"]
                     and re.sub(r"\d+", "<N>", r["msg"]) == p["signature"])
        assert actual == p["count"], p


def _text_io_calls_missing_encoding(py_path):
    """Find read_text()/write_text()/open() calls with no explicit encoding.

    Without an explicit encoding, these fall back to
    locale.getpreferredencoding(), which can be plain ASCII in a minimal/CI
    locale (this repo's own templates/instruction.md contains non-ASCII
    bytes, so reading it that way would raise UnicodeDecodeError). Binary
    ("...b..." mode) opens are exempt since encoding doesn't apply to them.
    """
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (func.attr if isinstance(func, ast.Attribute)
               else func.id if isinstance(func, ast.Name) else None)
        if name in ("read_text", "write_text"):
            if not any(kw.arg == "encoding" for kw in node.keywords):
                missing.append(f"{py_path.name}:{node.lineno}: {name}() missing encoding=")
        elif name == "open":
            mode = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value
            is_binary = isinstance(mode, str) and "b" in mode
            has_encoding = any(kw.arg == "encoding" for kw in node.keywords)
            if not is_binary and not has_encoding:
                missing.append(f"{py_path.name}:{node.lineno}: open() missing encoding=")
    return missing


def test_all_text_io_specifies_utf8_encoding():
    pkg_dir = Path(__file__).resolve().parent.parent  # tools/scenario_gen
    offenders = []
    for py in pkg_dir.glob("*.py"):
        offenders.extend(_text_io_calls_missing_encoding(py))
    assert not offenders, offenders


EXEMPLAR_DROPPED_BY_SAMPLING = FULL.replace(
    "[ground_truth]",
    '''[[incident.trace_exemplars]]
trace_id = "doomed-trace"
span_id = "s0"
parent_id = ""
service = "svc-a"
name = "handle"
start = "2026-07-20T09:31:00Z"
duration_ms = 120
status = "ERROR"

[[degradations]]
type = "sample_traces"
rate = 0.5

[ground_truth]''',
)


def test_sample_traces_dropping_trace_exemplar_rejected(scenario_dir):
    # "doomed-trace" hashes to 5088/10000 under the sample_traces md5 rule,
    # so a rate=0.5 (cut=5000) degradation silently dropped it pre-fix --
    # the grader's trace exemplar would vanish from traces.json with no
    # signal that the scenario was broken.
    (scenario_dir / "scenario.toml").write_text(EXEMPLAR_DROPPED_BY_SAMPLING)
    with pytest.raises(SpecError, match="sample_traces.*doomed-trace"):
        emit_scenario(scenario_dir / "scenario.toml")


def test_emit_is_deterministic(scenario_dir):
    emit_scenario(scenario_dir / "scenario.toml")
    first = (scenario_dir / "environment/data/logs.ndjson").read_bytes()
    emit_scenario(scenario_dir / "scenario.toml")
    assert (scenario_dir / "environment/data/logs.ndjson").read_bytes() == first
