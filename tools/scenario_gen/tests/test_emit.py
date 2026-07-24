import json
from pathlib import Path

import pytest

from tools.scenario_gen.emit import emit_scenario
from tools.scenario_gen.spec import SpecError
from tools.scenario_gen.tests.test_spec import MINIMAL

# MINIMAL lacks a non-culprit deploy near fired_at; add an innocent decoy deploy
# so the decoy-position consistency check passes.
FULL = MINIMAL.replace(
    "[ground_truth]",
    '''[[commits.authored]]
id = "decoy"
message = "chore: adjust css spacing on checkout page"
author = "sofia.rossi"
timestamp = "2026-07-20T09:38:00Z"
files = ["web/styles/checkout.css"]
diff = "--- a/web/styles/checkout.css\\n+++ b/web/styles/checkout.css\\n@@ -3 +3 @@\\n-margin: 4px\\n+margin: 6px\\n"

[[deploys]]
service = "svc-a"
commit = "decoy"
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


def test_emit_is_deterministic(scenario_dir):
    emit_scenario(scenario_dir / "scenario.toml")
    first = (scenario_dir / "environment/data/logs.ndjson").read_bytes()
    emit_scenario(scenario_dir / "scenario.toml")
    assert (scenario_dir / "environment/data/logs.ndjson").read_bytes() == first
