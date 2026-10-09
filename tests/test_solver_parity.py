"""The browser solver must reach the same optimum as an exact MILP."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import Bounds, LinearConstraint, milp

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
TYPES = ["opener", "batter", "keeper", "allrounder", "pace", "spin"]


def milp_optimum(inst: dict) -> float | None:
    cands = [c for c in inst["cands"] if c["id"] not in set(inst.get("excludes", []))]
    slots = [s for s in inst["slots"] if s["count"] > 0]
    var = [(i, s["type"]) for i, c in enumerate(cands) for s in slots if c["util"].get(s["type"]) is not None]
    if not var:
        return None
    n = len(var)
    cost = -np.array([cands[i]["util"][t] for i, t in var])
    rows, lo, hi = [], [], []
    for s in slots:  # each slot type filled exactly
        rows.append([1.0 if t == s["type"] else 0.0 for _, t in var]); lo.append(s["count"]); hi.append(s["count"])
    for i in range(len(cands)):  # each player at most once
        rows.append([1.0 if j == i else 0.0 for j, _ in var]); lo.append(0); hi.append(1)
    if inst.get("maxOverseas") is not None:
        rows.append([1.0 if cands[i].get("overseas") else 0.0 for i, _ in var]); lo.append(0); hi.append(inst["maxOverseas"])
    if inst.get("maxPerTeam") is not None:
        for team in {c["team"] for c in cands}:
            rows.append([1.0 if cands[i]["team"] == team else 0.0 for i, _ in var]); lo.append(0); hi.append(inst["maxPerTeam"])
    for lid in inst.get("locks", []):
        rows.append([1.0 if cands[i]["id"] == lid else 0.0 for i, _ in var]); lo.append(1); hi.append(1)
    res = milp(cost, constraints=LinearConstraint(np.array(rows), lo, hi), integrality=np.ones(n),
               bounds=Bounds(0, 1))
    return None if res.status != 0 else float(-res.fun)


def random_instance(rng: np.random.Generator, k: int) -> dict:
    n = int(rng.integers(25, 160))
    cands = []
    for i in range(n):
        util = {}
        for t in TYPES:
            if rng.random() < {"keeper": 0.12, "allrounder": 0.2}.get(t, 0.35):
                util[t] = round(float(rng.normal(55, 12)), 3)
        cands.append({"id": f"p{i}", "util": util, "overseas": bool(rng.random() < 0.35),
                      "team": f"T{int(rng.integers(0, 6))}"})
    counts = [2, 3, 1, 1, 3, 1] if k % 2 else [2, 2, 1, 2, 2, 2]
    inst = {"slots": [{"type": t, "count": c} for t, c in zip(TYPES, counts)], "cands": cands}
    if k % 3 == 0:
        inst["maxOverseas"] = 4
    elif k % 4 == 1:  # the two cap kinds are mutually exclusive by design
        inst["maxPerTeam"] = 3
    if k % 5 == 2:
        elig = [c["id"] for c in cands if c["util"]]
        inst["locks"] = [elig[int(rng.integers(0, len(elig)))]]
        inst["excludes"] = [elig[0]] if elig[0] not in inst["locks"] else []
    return inst


@pytest.mark.skipif(NODE is None, reason="node is required for the browser engine")
def test_js_solver_matches_milp(tmp_path):
    rng = np.random.default_rng(20261009)
    instances = [random_instance(rng, k) for k in range(120)]
    path = tmp_path / "instances.json"
    path.write_text(json.dumps(instances))
    out = subprocess.run([NODE, str(ROOT / "site" / "tests" / "solve_cli.mjs"), str(path)],
                         capture_output=True, text=True, check=True, cwd=ROOT)
    results = json.loads(out.stdout)
    checked = 0
    for inst, res in zip(instances, results):
        expected = milp_optimum(inst)
        if expected is None:
            assert "error" in res
            continue
        assert "error" not in res, res
        assert res["optimal"]
        assert res["total"] == pytest.approx(expected, abs=1e-6)
        assert len(set(res["ids"])) == sum(s["count"] for s in inst["slots"])
        checked += 1
    assert checked >= 90


@pytest.mark.skipif(NODE is None, reason="node is required for the browser engine")
def test_combined_caps_are_rejected(tmp_path):
    inst = random_instance(np.random.default_rng(1), 0)
    inst["maxOverseas"], inst["maxPerTeam"] = 4, 3
    path = tmp_path / "one.json"
    path.write_text(json.dumps([inst]))
    out = subprocess.run([NODE, str(ROOT / "site" / "tests" / "solve_cli.mjs"), str(path)],
                         capture_output=True, text=True, check=True, cwd=ROOT)
    assert "error" in json.loads(out.stdout)[0]
