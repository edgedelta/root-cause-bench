#!/usr/bin/env python3
"""RootCauseBench grader.

PRIMARY reward (pass/fail): the model's `root_cause_commit` must EXACTLY match
the ground-truth culprit SHA. Everything else is SECONDARY: we print it for the
write-up but never fail the test on it.

Besides the binary verdict, the grader emits a GRADED reward — 1.0 for the
correct commit; 0.0 if the model blamed an innocent-deploy decoy (the cardinal
failure); otherwise partial credit capped at 0.5 from the secondary diagnosis
(0.5 x first-failing-service + 0.3 x blast-radius Jaccard + 0.2 x remediation).
It is emitted as a `ROOTCAUSEBENCH_METRICS {json}` stdout line and, under
Harbor, /logs/verifier/metrics.json. It never changes pass/fail (reward.txt
stays binary); leaderboards use it to rank on mean graded reward instead of
coarse pass counts.

Ground truth lives in tests/ground_truth.json, which is injected only at
verification time, so the agent never sees it.
"""

import json
import os
import sys

ANSWER_PATH = "/workdir/root_cause.json"
GROUND_TRUTH_PATH = os.path.join(os.path.dirname(__file__), "ground_truth.json")
METRICS_PATH = os.environ.get("RCABENCH_METRICS_PATH", "/logs/verifier/metrics.json")


def _emit_metrics(metrics):
    print(f"ROOTCAUSEBENCH_METRICS {json.dumps(metrics, sort_keys=True)}")
    try:
        if os.path.isdir(os.path.dirname(METRICS_PATH)):
            with open(METRICS_PATH, "w") as f:
                json.dump(metrics, f, indent=1)
    except OSError:
        pass  # metrics file is best-effort; never fail grading over it

VALID_REMEDIATIONS = {
    "rollback", "roll-forward", "config-revert", "scale", "feature-flag-disable",
}


def _load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def _normalize_sha(s):
    return (s or "").strip().lower()


def _jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not (sa | sb):
        return 1.0
    return len(sa & sb) / len(sa | sb)


def test_answer_file_is_valid_json():
    assert os.path.exists(ANSWER_PATH), f"answer file {ANSWER_PATH} not found"
    data = _load_json(ANSWER_PATH)
    assert isinstance(data, dict), "root_cause.json must be a JSON object"
    assert "root_cause_commit" in data, "missing 'root_cause_commit'"
    assert "first_failing_service" in data, "missing 'first_failing_service'"
    assert "blast_radius" in data, "missing 'blast_radius'"
    assert "remediation" in data, "missing 'remediation'"
    assert isinstance(data["blast_radius"], list), "'blast_radius' must be a list"
    # remediation is free-form (operational answers like "scale"/"failover"/"rotate-cert"
    # are valid for no-code-cause incidents); only require a non-empty string. It is not
    # the graded axis — only root_cause_commit gates reward.
    assert isinstance(data["remediation"], str) and data["remediation"].strip(), (
        "'remediation' must be a non-empty string"
    )
    print("✓ root_cause.json parses and has the required schema")


def test_root_cause_commit_matches():
    """PRIMARY: exact culprit SHA match. This is the only assertion that gates reward."""
    answer = _load_json(ANSWER_PATH)
    truth = _load_json(GROUND_TRUTH_PATH)

    got = _normalize_sha(answer.get("root_cause_commit"))
    want = _normalize_sha(truth["root_cause_commit"])

    # Accept a correct unambiguous short SHA (>=7 hex chars) as a prefix match.
    is_match = (got == want) or (len(got) >= 7 and want.startswith(got))

    # ---- SECONDARY metrics (printed, never fatal) -------------------------
    svc_got = (answer.get("first_failing_service") or "").strip()
    svc_want = truth["first_failing_service"]
    svc_correct = svc_got == svc_want

    br_got = [s.strip() for s in answer.get("blast_radius", [])]
    br_want = truth["blast_radius"]
    br_jaccard = _jaccard(br_got, br_want)

    decoy_shas = {_normalize_sha(s) for s in truth.get("decoy_deploy_commits", [])}
    fell_for_decoy = got in decoy_shas

    rem_got = answer.get("remediation")
    rem_correct = rem_got == truth["remediation"]

    print("\n================ SECONDARY METRICS (not graded) ================")
    print(f"scenario                  : {truth.get('scenario')}")
    print(f"root_cause_commit correct : {is_match}  (got {got[:12]} / want {want[:12]})")
    print(f"first_failing_service     : {svc_correct}  (got {svc_got!r} / want {svc_want!r})")
    print(f"blast_radius Jaccard      : {br_jaccard:.2f}  (got {br_got} / want {br_want})")
    print(f"remediation correct       : {rem_correct}  (got {rem_got!r} / want {truth['remediation']!r})")
    print(f"fell_for_innocent_decoy   : {fell_for_decoy}", end="")
    if fell_for_decoy:
        print("  <-- model blamed a commit from the innocent/decoy deploy")
    else:
        print("")
    print("===============================================================\n")

    if is_match:
        graded = 1.0
    elif fell_for_decoy:
        graded = 0.0
    else:
        graded = round(0.5 * (0.5 * svc_correct + 0.3 * br_jaccard + 0.2 * rem_correct), 4)
    _emit_metrics({
        "scenario": truth.get("scenario"),
        "sha_correct": is_match,
        "first_failing_service_correct": svc_correct,
        "blast_radius_jaccard": round(br_jaccard, 4),
        "remediation_correct": rem_correct,
        "fell_for_decoy": fell_for_decoy,
        "graded_reward": graded,
    })

    # ---- PRIMARY assertion ------------------------------------------------
    assert is_match, (
        f"WRONG ROOT-CAUSE COMMIT. got={got!r} want={want!r}. "
        + ("Model fell for the innocent-deploy decoy. " if fell_for_decoy else "")
        + f"(hint for analysis: {truth.get('notes', '')})"
    )
    print("✓ root_cause_commit matches ground truth")


if __name__ == "__main__":
    try:
        test_answer_file_is_valid_json()
        test_root_cause_commit_matches()
        print("\nAll tests passed!")
        sys.exit(0)
    except AssertionError as e:
        print(f"\nTest failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
