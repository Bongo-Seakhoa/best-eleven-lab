"""XI vs XI calibration: the fits recover known parameters, the match list keeps
only completed full-length matches, and the Node harness projects real elevens
through the site engine without looking at the match's own season."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from best_eleven.model import calibrate as cal
from best_eleven.validate import VERSUS_CHECK, versus_check

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "versus"
NODE = shutil.which("node")
sigmoid = lambda z: 1 / (1 + np.exp(-z))  # noqa: E731


# --- fitting ---------------------------------------------------------------


def test_logistic_fit_recovers_k_and_home():
    rng = np.random.default_rng(7)
    n, k, h = 40_000, 0.05, 0.3
    edge = rng.normal(0, 20, n)
    home = rng.choice([-1, 0, 1], n)
    y = (rng.random(n) < sigmoid(k * edge + h * home)).astype(float)
    f = cal.fit_logistic(edge, y, home)
    assert f["k"] == pytest.approx(k, rel=0.05)
    assert f["home"] == pytest.approx(h, abs=0.05)


def test_logistic_fit_takes_ties_as_half():
    edge = np.array([-10.0, 10.0] * 500)
    assert cal.fit_logistic(edge, np.full(len(edge), 0.5))["k"] == pytest.approx(0, abs=1e-6)


def test_ordered_fit_recovers_k_and_c():
    rng = np.random.default_rng(11)
    n, k, c, h = 40_000, 0.008, 0.6, 0.5
    edge = rng.normal(0, 100, n)
    home = rng.choice([-1, 0, 1], n)
    P = cal.ordered_probs(edge, k, c, home, h)
    u = rng.random(n)
    outcome = np.where(u < P[:, 0], 0, np.where(u < P[:, 0] + P[:, 1], 1, 2))
    f = cal.fit_ordered(edge, outcome, home)
    assert f["k"] == pytest.approx(k, rel=0.06)
    assert f["c"] == pytest.approx(c, rel=0.06)
    assert f["home"] == pytest.approx(h, abs=0.06)


def test_ordered_probabilities_are_symmetric_and_sum_to_one():
    P = cal.ordered_probs(np.array([-50.0, 0.0, 50.0]), 0.01, 0.5)
    assert np.allclose(P.sum(axis=1), 1)
    assert P[0, 2] == pytest.approx(P[2, 0]) and P[1, 0] == pytest.approx(P[1, 2])


def test_evaluation_against_the_naive_forecasts():
    edge = np.array([20.0, -20.0, 20.0, 0.0])
    y = np.array([1.0, 0.0, 0.0, 0.5])
    ev = cal.evaluate_binary(edge, y, 0.05)
    p = sigmoid(0.05 * edge)
    assert ev["brier"] == pytest.approx(np.mean((p - y) ** 2))
    assert ev["brierBaseline"] == pytest.approx(0.75 / 4)
    assert ev["logLossBaseline"] == pytest.approx(np.log(2))
    assert ev["accuracy"] == pytest.approx(2 / 3)       # the tie and the level match are not judged
    bins = cal.evaluate_binary(np.linspace(-40, 40, 101), np.ones(101), 0.05)["bins"]
    assert bins[0]["lo"] == 0.5 and bins[-1]["hi"] == 1.0 and sum(b["n"] for b in bins) == 101
    assert all(a["hi"] == b["lo"] for a, b in zip(bins, bins[1:]))
    o = np.array([2, 1, 0, 2])
    et = cal.evaluate_ordered(np.array([30.0, 0.0, -30.0, -10.0]), o, 0.01, 0.5, p_draw=0.2)
    base = np.array([0.4, 0.2, 0.4])
    assert et["brierBaseline"] == pytest.approx(np.mean([np.sum((base - np.eye(3)[i]) ** 2) for i in o]))
    assert et["accuracy"] == pytest.approx(2 / 3)


def test_forward_check_needs_the_curve_to_travel_within_training_years():
    rng = np.random.default_rng(3)
    rows = []
    for year in range(2010, 2021):
        edge = rng.normal(0, 20, 120)
        u = rng.random(120)
        rows.append(pd.DataFrame({"year": year, "edge": edge, "home": 0,
                                  "steady": (u < sigmoid(0.08 * edge)).astype(float),
                                  # the relation reverses in the last three seasons
                                  "broken": (u < sigmoid((0.08 if year < 2018 else -0.08) * edge)).astype(float)}))
    d = pd.concat(rows, ignore_index=True)
    ok = cal.forward_check(d.assign(outcome=d["steady"]), tests=False)
    assert ok["passed"] and ok["years"] == [2018, 2019, 2020] and ok["n"] == 360
    assert not cal.forward_check(d.assign(outcome=d["broken"]), tests=False)["passed"]
    assert not cal.forward_check(d[d["year"] < 2011].assign(outcome=d["steady"]), tests=False)["passed"]


# --- the build check ---------------------------------------------------------


def _group(n_test, brier, base=0.25):
    return {"label": "G", "nTest": n_test, "brier": brier, "brierBaseline": base, "logLoss": 0.6,
            "logLossBaseline": 0.69, "accuracy": 0.6}


def test_versus_check_judges_groups_with_enough_held_out_matches():
    assert versus_check({"a": _group(250, 0.22), "b": _group(120, 0.26)})["passed"]
    failed = versus_check({"a": _group(250, 0.22), "b": _group(200, 0.26)})
    assert not failed["passed"] and failed["name"] == VERSUS_CHECK
    assert not versus_check({"a": _group(120, 0.2)})["passed"]       # nothing big enough to judge
    assert not versus_check({})["passed"]


# --- match list ----------------------------------------------------------------


def _warehouse(tmp: Path) -> None:
    teams = {"India": "IN", "Australia": "AU", "Nepal": "NP", "Stars": "ST", "Heat": "HT"}
    ids = {t: [f"{code}{i}" for i in range(1, 12)] for t, code in teams.items()}
    players = pd.DataFrame({"id": [x for v in ids.values() for x in v]})
    players["player"] = np.arange(len(players), dtype=np.int32)
    num = dict(zip(players["id"], players["player"]))

    def match(mid, t1, t2, *, family="t20", result="win", winner=None, method="", eliminator="",
              team_type="international", scope="men-t20i", year=2019):
        return {"match_id": mid, "year": year, "family": family, "gender": "male", "team_type": team_type,
                "scope": scope, "team1": t1, "team2": t2, "result": result, "winner": winner or "",
                "method": method, "eliminator": eliminator, "overs": 20.0 if family != "multi" else np.nan,
                "bpo": 6, "city": "Perth", "venue": "Perth Stadium"}

    m = pd.DataFrame([
        match(1, "India", "Australia", winner="India"),
        match(2, "India", "Nepal", winner="India"),
        match(3, "India", "Australia", result="no result"),
        match(4, "India", "Australia", winner="Australia", method="D/L"),
        match(5, "India", "Australia", result="tie", eliminator="India"),
        match(6, "India", "Australia", result="tie"),
        match(7, "India", "Australia", winner="Australia"),
        match(8, "India", "Australia", family="multi", result="draw", scope="men-test"),
        match(9, "Stars", "Heat", winner="Heat", team_type="club", scope="bbl"),
    ])
    inn, bat, app = [], [], []
    for r in m.itertuples():
        for i, (team, opp) in enumerate([(r.team1, r.team2), (r.team2, r.team1)], start=1):
            reduced = r.match_id == 7 and i == 2
            inn.append({"match_id": r.match_id, "inning": i, "batting_team": team, "super_over": 0,
                        "max_balls": 60 if reduced else (-1 if r.family == "multi" else 120)})
            for p in ids[team]:
                app.append({"match_id": r.match_id, "team": team, "player": num[p]})
            # Each side bats its 11th player first and its 1st player second; the rest do not bat.
            for pos, p in enumerate([ids[team][10], ids[team][0]], start=1):
                bat.append({"match_id": r.match_id, "inning": i, "team": team, "player": num[p],
                            "position": pos, "super_over": 0})
        if r.match_id == 1:  # a super over must not set the batting order
            bat.append({"match_id": 1, "inning": 3, "team": "India", "player": num["IN5"], "position": 1,
                        "super_over": 1})
    m.to_parquet(tmp / "matches.parquet")
    pd.DataFrame(inn).to_parquet(tmp / "innings.parquet")
    pd.DataFrame(bat).to_parquet(tmp / "batting.parquet")
    pd.DataFrame(app).to_parquet(tmp / "appearances.parquet")
    players.to_parquet(tmp / "players.parquet")


def test_match_list_keeps_completed_full_length_matches(tmp_path):
    _warehouse(tmp_path)
    m, skipped = cal.match_list(tmp_path, ["men-t20i", "men-test", "bbl"])
    assert sorted(m["match_id"]) == [1, 6, 8, 9]
    assert skipped == {"not between Full Members": 1, "no result": 1, "decided by a rain rule or awarded": 1,
                       "tie settled by a super over": 1, "overs reduced": 1}
    out = m.set_index("match_id")["outcome"]
    assert out[1] == 1.0 and out[6] == 0.5 and out[8] == 1.0 and out[9] == 0.0
    first = m.set_index("match_id").loc[1]
    assert first["a"] == ["IN11", "IN1", "IN2", "IN3", "IN4", "IN5", "IN6", "IN7", "IN8", "IN9", "IN10"]
    assert first["b"][:3] == ["AU11", "AU1", "AU2"]


# --- the Node harness --------------------------------------------------------------


def _side(prefix, order=None):
    ids = [f"{prefix}{i}" for i in range(1, 12)]
    return [ids[i] for i in order] if order else ids


@pytest.mark.skipif(NODE is None, reason="node is required for the browser engine")
def test_harness_projects_through_the_site_engine(tmp_path):
    groups = json.loads((FIX / "groups.json").read_text(encoding="utf-8"))
    matches = [
        {"id": 1, "scope": "demo", "year": 2020, "a": _side("n"), "b": _side("s")},
        {"id": 2, "scope": "demo", "year": 2016, "a": _side("n"), "b": _side("s")},
        {"id": 3, "scope": "demo", "year": 2020, "a": _side("n", [1, 0, *range(2, 11)]), "b": _side("s")},
        {"id": 4, "scope": "demo", "year": 2020, "a": _side("n"), "b": [*_side("s")[:10], "unknown"]},
        {"id": 5, "scope": "demo", "year": 2010, "a": _side("n"), "b": _side("s")},
    ]
    src, dst = tmp_path / "in.json", tmp_path / "out.json"
    src.write_text(json.dumps({"scopesDir": str(FIX), "groups": groups, "window": 4, "halfLife": 3,
                               "matches": matches}))
    subprocess.run([NODE, str(ROOT / "site" / "cli" / "versus-calibrate.mjs"), str(src), str(dst)],
                   capture_output=True, text=True, check=True, cwd=ROOT)
    out = {r["id"]: r for r in json.loads(dst.read_text())}
    assert {r["key"] for r in out.values()} == {"national:male:t20"}
    # Match in 2020 rates from 2016-19 with a 3-year half-life; 2015 and 2020 rows are ignored.
    # n1 bats: (10 + 0.5*20) / (100 + 0.5*100 + 100 lambda) = 0.08 a ball, 20% of 100 balls -> +1.6.
    # s1 bowls 20% (quota) at 6 / (60 + 100) = 0.0375 a ball saved -> 0.75 off North's score.
    assert out[1]["edge"] == pytest.approx(1.6 - 0.75)
    assert out[1]["scoreA"] == pytest.approx(150.85) and out[1]["scoreB"] == pytest.approx(150)
    assert out[1]["rated"] == [2, 1]
    # 2016 rates from 2012-15 only: 50 / (100 + 100) = 0.25 a ball, and s1 has no record yet.
    assert out[2]["edge"] == pytest.approx(0.2 * 100 * 0.25)
    assert out[2]["rated"] == [1, 0]
    # n1 at number two faces 15% of the innings.
    assert out[3]["edge"] == pytest.approx(0.15 * 100 * 0.08 - 0.75)
    assert out[4]["edge"] == pytest.approx(out[1]["edge"]) and out[4]["rated"] == [2, 1]
    assert out[5]["edge"] == 0 and out[5]["rated"] == [0, 0]


# --- pipeline step -------------------------------------------------------------------


def test_calibration_refuses_to_run_without_node(tmp_path, monkeypatch):
    from best_eleven import pipeline as pl
    p = pl.Paths(tmp_path)
    path = p.site_data / "model" / "versus.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"groups":{}}', encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda *_: None)
    with pytest.raises(RuntimeError, match="Node.js"):
        pl.calibrate(p)
    assert json.loads(path.read_text(encoding="utf-8")) == {"groups": {}}


def test_recorded_check_replaces_its_earlier_result(tmp_path):
    from best_eleven import pipeline as pl
    p = pl.Paths(tmp_path)
    p.model.mkdir(parents=True)
    (p.model / "validation.json").write_text(json.dumps({"checks": [
        {"name": "Margins", "passed": True}, {"name": VERSUS_CHECK, "passed": False}]}), encoding="utf-8")
    pl.record_check(p, {"name": VERSUS_CHECK, "passed": True})
    for path in (p.model / "validation.json", p.site_data / "validation.json"):
        checks = json.loads(path.read_text(encoding="utf-8"))["checks"]
        assert [(c["name"], c["passed"]) for c in checks] == [("Margins", True), (VERSUS_CHECK, True)]
