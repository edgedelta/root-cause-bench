#!/usr/bin/env python3
"""RootCauseBench oracle + data-integrity check (no Docker needed).

For every scenario under datasets/rootcausebench/ this verifies:

  1. STRUCTURE   — ground_truth is internally consistent and resolves against
                   the data the agent sees: root_cause_commit is "none" or a
                   SHA present in context/commits.json; every decoy commit and
                   every deploy's commit_sha resolves; alert.json parses and
                   names a service.
  2. SOLVE.SH    — replaying solution/solve.sh (with /workdir redirected to a
                   temp dir) emits a valid root_cause.json.
  3. ORACLE      — the emitted answer matches ground truth on every field
                   (commit, first_failing_service, blast_radius set,
                   remediation), not just the graded one.
  4. GRADER      — the scenario's real grader (tests/test_outputs.py) passes
                   both checks (schema + primary SHA match) on the oracle.

Exit code 0 = every scenario clean. Run by CI on every push/PR.
"""

import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATASET = REPO / "datasets" / "rootcausebench"

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def fail(scenario, msg):
    print(f"  FAIL [{scenario}] {msg}")
    return 1


def check_structure(name, d):
    errors = 0
    data = d / "environment" / "data"
    gt = json.loads((d / "tests" / "ground_truth.json").read_text())
    commits = json.loads((data / "context" / "commits.json").read_text())
    deploys = json.loads((data / "context" / "deploys.json").read_text())
    alert = json.loads((data / "alert.json").read_text())

    shas = {c["sha"] for c in commits}
    culprit = gt["root_cause_commit"]
    if culprit != "none":
        if not SHA_RE.match(culprit):
            errors += fail(name, f"root_cause_commit {culprit!r} is not a full lowercase sha")
        elif culprit not in shas:
            errors += fail(name, f"root_cause_commit {culprit[:12]} not in commits.json")
    for sha in gt.get("decoy_deploy_commits", []):
        if sha not in shas:
            errors += fail(name, f"decoy commit {sha[:12]} not in commits.json")
        if sha == culprit:
            errors += fail(name, f"decoy commit {sha[:12]} equals the culprit")
    for dep in deploys:
        if dep["commit_sha"] not in shas:
            errors += fail(name, f"deploy {dep.get('version')} commit {dep['commit_sha'][:12]} "
                                 f"not in commits.json")
    if not (gt.get("first_failing_service") or "").strip():
        errors += fail(name, "first_failing_service empty")
    if not isinstance(gt.get("blast_radius"), list):
        errors += fail(name, "blast_radius is not a list")
    if not (gt.get("remediation") or "").strip():
        errors += fail(name, "remediation empty")
    if not alert.get("fired_at") or not alert.get("service"):
        errors += fail(name, "alert.json missing fired_at/service")
    return errors, gt


def replay_solve_sh(name, d):
    """Replay solve.sh into a temp dir; return (errors, emitted answer dict)."""
    solve = d / "solution" / "solve.sh"
    with tempfile.TemporaryDirectory() as tmp:
        script = solve.read_text().replace("/workdir", tmp)
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        if r.returncode != 0:
            return fail(name, f"solve.sh failed: {r.stderr.strip()[:200]}"), None
        emitted_path = Path(tmp) / "root_cause.json"
        if not emitted_path.exists():
            return fail(name, "solve.sh did not write root_cause.json"), None
        return 0, json.loads(emitted_path.read_text())


def check_oracle_matches_truth(name, answer, gt):
    errors = 0
    if answer["root_cause_commit"].strip().lower() != gt["root_cause_commit"].strip().lower():
        errors += fail(name, f"oracle commit {answer['root_cause_commit'][:12]} != "
                             f"truth {gt['root_cause_commit'][:12]}")
    if answer["first_failing_service"].strip() != gt["first_failing_service"]:
        errors += fail(name, f"oracle first_failing_service {answer['first_failing_service']!r} "
                             f"!= truth {gt['first_failing_service']!r}")
    if set(answer["blast_radius"]) != set(gt["blast_radius"]):
        errors += fail(name, f"oracle blast_radius {sorted(answer['blast_radius'])} "
                             f"!= truth {sorted(gt['blast_radius'])}")
    if answer["remediation"] != gt["remediation"]:
        errors += fail(name, f"oracle remediation {answer['remediation']!r} "
                             f"!= truth {gt['remediation']!r}")
    return errors


def check_grader_passes_oracle(name, d, answer):
    errors = 0
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "root_cause.json").write_text(json.dumps(answer))
        spec = importlib.util.spec_from_file_location(
            f"grader_{name.replace('-', '_')}", d / "tests" / "test_outputs.py")
        grader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(grader)
        grader.ANSWER_PATH = str(Path(tmp) / "root_cause.json")
        for test in (grader.test_answer_file_is_valid_json,
                     grader.test_root_cause_commit_matches):
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    test()
            except AssertionError as e:
                print(buf.getvalue(), end="")
                errors += fail(name, f"grader rejected the oracle: {e}")
    return errors


def main():
    scenarios = sorted(p for p in DATASET.iterdir()
                       if (p / "tests" / "ground_truth.json").exists())
    if not scenarios:
        print(f"no scenarios found under {DATASET}")
        sys.exit(1)

    total_errors = 0
    for d in scenarios:
        name = d.name
        errs, gt = check_structure(name, d)
        solve_errs, answer = replay_solve_sh(name, d)
        errs += solve_errs
        if answer is not None:
            errs += check_oracle_matches_truth(name, answer, gt)
            errs += check_grader_passes_oracle(name, d, answer)
        kind = "no-code-cause" if gt["root_cause_commit"] == "none" else "real-culprit"
        status = "OK  " if errs == 0 else "FAIL"
        print(f"{status} {name}  ({kind}, decoys={len(gt.get('decoy_deploy_commits', []))})")
        total_errors += errs

    print(f"\n{len(scenarios)} scenarios checked, "
          f"{'all clean' if total_errors == 0 else f'{total_errors} error(s)'}")
    sys.exit(1 if total_errors else 0)


if __name__ == "__main__":
    main()
