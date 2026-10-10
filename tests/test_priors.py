"""Priors for short records (src/best_eleven/model/priors.py), on synthetic data.

The numbers below are invented to test the arithmetic; they are not cricket records.
"""
import numpy as np
import pandas as pd
import pytest

from best_eleven.model import priors as pr


def _career(rates, balls, kind="bat"):
    """A unit's career table from per-player rates and balls (bowling rates are runs saved)."""
    rates, balls = np.asarray(rates, float), np.asarray(balls, float)
    df = pd.DataFrame({"m": balls / 30, "b": 0.0, "ba": 0.0, "wb": 0.0, "wc": 0.0}, index=pd.RangeIndex(len(rates), name="player"))
    if kind == "bat":
        df["b"], df["ba"] = balls, rates * balls
    else:
        df["wb"], df["wc"] = balls, -rates * balls
    return df


def test_transfer_recovers_slope_and_offset():
    rng = np.random.default_rng(7)
    true = rng.normal(0, 0.15, 400)
    car = {"tgt": _career(0.03 + 0.7 * true + rng.normal(0, 0.01, 400), np.full(400, 20000)),
           "src": _career(true, np.full(400, 20000))}
    fits = pr.fit_transfers(car, "tgt", ["src"], "bat", {"tgt": 300.0, "src": 300.0})
    f = fits["src"]
    assert f["alpha"] == pytest.approx(0.03, abs=0.005)
    assert f["beta"] == pytest.approx(0.7 * (20000 + 300) / 20000, rel=0.03)   # source rate is shrunk before fitting
    assert f["n"] == 400


def test_transfer_needs_enough_shared_players():
    car = {"tgt": _career([0.1] * 10, [5000] * 10), "src": _career([0.1] * 10, [5000] * 10)}
    assert pr.fit_transfers(car, "tgt", ["src"], "bat", {"tgt": 300.0, "src": 300.0}) == {}


def test_prior_moves_from_baseline_with_the_source_sample():
    fits = {"src": {"alpha": 0.0, "beta": 1.0, "resid_var": 0.01, "n": 100, "r": 0.5}}
    car = {"src": _career([0.5, 0.5, 0.5], [20, 2000, 200000])}
    base, base_var = -0.2, 0.02
    p = pr.predict(car, fits, "bat", {"src": 300.0}, base, base_var, pd.Index([0, 1, 2, 3]))
    # Player 3 has no source record: he gets the baseline.
    assert p[3] == pytest.approx(base)
    # More balls elsewhere, more weight on what they predict.
    assert base < p[0] < p[1] < p[2] < 0.5
    # A long record is a precision blend: transfer weight ~1/0.01 against baseline weight 1/0.02.
    rel = 200000 / (200000 + 300)
    want = (rel / 0.01 * 0.5 * (200000 / 200300) + base / base_var) / (rel / 0.01 + 1 / base_var)
    assert p[2] == pytest.approx(want, rel=1e-6)


def test_bowling_rates_are_runs_saved():
    car = {"tgt": _career([0.2] * 30, [3000] * 30, "bowl"), "src": _career([0.2] * 30, [3000] * 30, "bowl")}
    rate = pr._rate(car["tgt"], "bowl")
    assert rate.iloc[0] == pytest.approx(0.2)


def test_newcomer_baseline_uses_first_seasons_only():
    d = pd.DataFrame({"player": [1, 1, 2, 2], "year": [2010, 2011, 2012, 2013],
                      "m": [5, 5, 5, 5], "b": [100, 900, 300, 700], "ba": [-30.0, 90.0, -30.0, 70.0],
                      "wb": [0, 0, 0, 0], "wc": [0.0, 0.0, 0.0, 0.0]})
    assert pr.newcomer_baseline({"u": d}, "u", "bat") == pytest.approx(-60 / 400)
    assert pr.newcomer_baseline({"u": d}, "u", "bat", before=2012) == pytest.approx(-30 / 100)


def test_part_time_rate_counts_occasional_bowlers_only():
    car = {"u": pd.DataFrame({"m": [10, 10, 10], "b": [0, 0, 0], "ba": [0.0] * 3,
                              "wb": [600, 40, 20], "wc": [-60.0, 20.0, 10.0]})}
    # 600 balls in 10 matches is a regular; 40 balls qualifies; 20 balls is too few to count.
    assert pr.part_time_rate(car, "u") == pytest.approx(-20 / 40)
    assert pr.part_time_rate(car, "missing") is None
