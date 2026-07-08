"""Extract per-trial graded metrics from a Harbor trial directory.

The RootCauseBench grader emits a graded reward (1.0 for the correct culprit
SHA; 0.0 for blaming an innocent-deploy decoy; otherwise partial credit capped
at 0.5 from the secondary diagnosis). Sources, in order:

  1. verifier/metrics.json            — written by graders from 2026-07 on
  2. ROOTCAUSEBENCH_METRICS line      — grader stdout (test-stdout.txt / pytest.log)
  3. legacy stdout                    — the "SECONDARY METRICS" block older
                                        graders printed; graded is recomputed
                                        with the same formula
  4. verifier ran but nothing parses  — grader asserted before scoring (missing/
                                        malformed root_cause.json): graded 0.0
  5. no verifier output at all        — harness error; returns None

Returns a dict with at least {"graded_reward": float} or None.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_LEGACY = {
    "sha_correct": re.compile(r"root_cause_commit correct : (True|False)"),
    "first_failing_service_correct": re.compile(r"first_failing_service\s+: (True|False)"),
    "blast_radius_jaccard": re.compile(r"blast_radius Jaccard\s+: ([\d.]+)"),
    "remediation_correct": re.compile(r"remediation correct\s+: (True|False)"),
    "fell_for_decoy": re.compile(r"fell_for_innocent_decoy\s+: (True|False)"),
}


def _graded(m):
    if m["sha_correct"]:
        return 1.0
    if m["fell_for_decoy"]:
        return 0.0
    return round(0.5 * (0.5 * m["first_failing_service_correct"]
                        + 0.3 * m["blast_radius_jaccard"]
                        + 0.2 * m["remediation_correct"]), 4)


def _from_stdout(text: str) -> dict | None:
    for line in text.splitlines():
        if line.startswith("ROOTCAUSEBENCH_METRICS "):
            try:
                return json.loads(line.split(" ", 1)[1])
            except json.JSONDecodeError:
                continue
    m = {}
    for key, rx in _LEGACY.items():
        hit = rx.search(text)
        if not hit:
            return None
        m[key] = float(hit.group(1)) if key == "blast_radius_jaccard" else hit.group(1) == "True"
    m["graded_reward"] = _graded(m)
    return m


def graded_of(trial_dir: Path) -> dict | None:
    verifier = Path(trial_dir) / "verifier"
    mf = verifier / "metrics.json"
    if mf.exists():
        try:
            return json.loads(mf.read_text())
        except json.JSONDecodeError:
            pass
    for name in ("test-stdout.txt", "pytest.log"):
        f = verifier / name
        if f.exists():
            m = _from_stdout(f.read_text(errors="replace"))
            if m:
                return m
    if (verifier / "reward.txt").exists():
        # Verifier ran but the grader never reached scoring: total failure.
        return {"graded_reward": 0.0}
    return None
