"""Run expectancy and per-delivery run value.

Limited overs: RE(u, w) is the expected number of further runs in an innings
with ``u`` legal balls left and ``w`` wickets down. It is fitted from complete,
full-length first innings with the Duckworth-Lewis functional form
``Z0(w) * (1 - exp(-b(w) * u))`` per wickets-lost level and era block, then
made monotone (fewer wickets in hand never raises expectation).

A delivery's value to the batting side is runs + RE(after) - RE(before). The
change splits into the cost of using up a legal ball and the cost of any
wicket, which lets batters and bowlers be credited separately.

Tests: there is no balls-remaining clock, so value is runs minus each dismissal
priced at that year's runs per wicket (``W``), which centres per-ball value at
zero for an average batter of that year.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

FAMILY_BALLS = {"t20": 120, "fifty": 300, "hundred": 100}
# Upper year of each era block; the last block is open-ended.
ERA_BREAKS = {"t20": [2012, 2018, 2022], "fifty": [2010, 2018], "hundred": []}
MIN_INNINGS_PER_ERA = 300


def era_index(family: str, years) -> np.ndarray:
    return np.searchsorted(np.asarray(ERA_BREAKS[family]), np.asarray(years), side="left")


def era_labels(family: str, first: int = 2002, last: int = 2026) -> list[str]:
    edges = [first - 1] + ERA_BREAKS[family] + [last]
    return [f"{a + 1}-{b}" for a, b in zip(edges[:-1], edges[1:])]


def _dl(u, z0, b):
    return z0 * (1.0 - np.exp(-b * u))


@dataclass
class RunExpectancy:
    family: str
    gender: str
    table: np.ndarray                 # [era, u (0..max_balls), w (0..10)]
    params: list = field(default_factory=list)
    innings_used: list = field(default_factory=list)

    def __call__(self, era, u, w):
        era = np.asarray(era); u = np.asarray(u); w = np.asarray(w)
        uc = np.clip(u, 0, self.table.shape[1] - 1)
        wc = np.clip(w, 0, 10)
        val = self.table[era, uc, wc]
        return np.where((u <= 0) | (w >= 10), 0.0, val)

    def to_json(self) -> dict:
        labels = era_labels(self.family)[: self.table.shape[0]]
        step = 6 if self.family != "hundred" else 5
        us = list(range(0, self.table.shape[1], step))
        return {"family": self.family, "gender": self.gender, "eras": labels,
                "balls": us, "innings_used": self.innings_used,
                "re": [[[round(float(self.table[e, u, w]), 2) for w in range(10)] for u in us]
                       for e in range(self.table.shape[0])]}


def remaining_runs_cells(deliveries: pd.DataFrame, family: str) -> pd.DataFrame:
    """Aggregate (era, u, w) -> count, sum of runs still to come, from complete
    full-length first innings. ``deliveries`` needs year, inning, super_over,
    balls_rem, legal_before, wkts_before, score_before, runs_total, match_id,
    method, innings_total, innings_wickets, innings_legal, max_balls."""
    full = FAMILY_BALLS[family]
    d = deliveries
    keep = ((d["inning"] == 1) & (d["super_over"] == 0) & (d["max_balls"] == full)
            & (d["method"] == "") & ((d["innings_wickets"] >= 10) | (d["innings_legal"] >= full)))
    d = d.loc[keep]
    era = era_index(family, d["year"].to_numpy())
    out = pd.DataFrame({"era": era, "u": d["balls_rem"].to_numpy(), "w": d["wkts_before"].to_numpy(),
                        "rem": (d["innings_total"] - d["score_before"]).to_numpy(),
                        "match_id": d["match_id"].to_numpy()})
    cells = out.groupby(["era", "u", "w"], as_index=False).agg(n=("rem", "size"), runs=("rem", "sum"))
    innings = out.groupby("era")["match_id"].nunique()
    cells.attrs["innings"] = innings.to_dict()
    return cells


def fit_run_expectancy(cells: pd.DataFrame, family: str, gender: str) -> RunExpectancy:
    full = FAMILY_BALLS[family]
    n_eras = len(ERA_BREAKS[family]) + 1
    innings = cells.attrs.get("innings", {})
    pooled = cells.groupby(["u", "w"], as_index=False)[["n", "runs"]].sum()
    table = np.zeros((n_eras, full + 1, 11))
    params, used = [], []
    u_axis = np.arange(full + 1, dtype=float)

    def fit_one(c: pd.DataFrame, prior=None):
        res = np.zeros((full + 1, 11)); ps = []
        for w in range(10):
            cw = c[(c["w"] == w) & (c["u"] > 0) & (c["n"] >= 5)]
            if cw["n"].sum() < 400 and prior is not None:
                res[:, w] = prior[:, w]; ps.append(None); continue
            if len(cw) < 4:
                res[:, w] = res[:, w - 1] * 0.8 if w else 0; ps.append(None); continue
            y = (cw["runs"] / cw["n"]).to_numpy(); u = cw["u"].to_numpy(float)
            sigma = 1.0 / np.sqrt(cw["n"].to_numpy())
            try:
                (z0, b), _ = curve_fit(_dl, u, y, p0=(max(y.max() * 1.3, 10.0), 0.02),
                                       sigma=sigma, bounds=([0.5, 1e-4], [1500.0, 1.0]), maxfev=20000)
            except RuntimeError:
                z0, b = y.max(), 0.02
            res[:, w] = _dl(u_axis, z0, b); ps.append((round(float(z0), 2), round(float(b), 5)))
        res[0, :] = 0.0
        res[:, 10] = 0.0
        return np.minimum.accumulate(res, axis=1), ps

    pooled_table, pooled_params = fit_one(pooled)
    for e in range(n_eras):
        ce = cells[cells["era"] == e]
        if innings.get(e, 0) >= MIN_INNINGS_PER_ERA:
            table[e], ps = fit_one(ce, prior=pooled_table)
        else:
            table[e], ps = pooled_table, pooled_params
        params.append(ps); used.append(int(innings.get(e, 0)))
    return RunExpectancy(family, gender, table, params, used)


def test_wicket_value(dlv: pd.DataFrame) -> pd.Series:
    """Runs per dismissal by year (batter runs / dismissals of batters)."""
    g = dlv[dlv["super_over"] == 0].groupby("year")
    w = g["runs_batter"].sum() / (g["striker_out"].sum() + g["ns_out"].sum()).clip(lower=1)
    return w


def delivery_values(d: pd.DataFrame, family: str, re: RunExpectancy | None,
                    test_w: pd.Series | None) -> pd.DataFrame:
    """Add value columns to deliveries.

    contest: value of a faced ball to the batting side attributable to the
        batter-bowler contest (batter runs, ball consumed, striker dismissal).
    extras_cost: wides + no-ball runs, charged to the bowler only.
    ns_wicket: value lost through a non-striker dismissal (run outs).
    """
    rb = d["runs_batter"].to_numpy(float)
    striker_out = d["striker_out"].to_numpy()
    ns_out = d["ns_out"].to_numpy()
    if family == "multi":
        wv = d["year"].map(test_w).to_numpy(float)
        contest = rb - wv * striker_out
        ns_val = -wv * ns_out
    else:
        era = era_index(family, d["year"].to_numpy())
        u = d["balls_rem"].to_numpy().astype(int)
        w = d["wkts_before"].to_numpy().astype(int)
        legal = d["legal"].to_numpy().astype(int)
        u2 = u - legal
        r0 = re(era, u, w)
        r1 = re(era, u2, w)
        prog = r1 - r0
        w_s = re(era, u2, w + striker_out) - r1
        w_ns = re(era, u2, w + striker_out + ns_out) - re(era, u2, w + striker_out)
        contest = rb + prog + w_s
        ns_val = w_ns
    out = d.copy()
    out["contest"] = contest.astype(np.float32)
    out["extras_cost"] = (d["wides"] + d["noballs"]).astype(np.float32)
    out["ns_value"] = np.asarray(ns_val, dtype=np.float32)
    return out


def save_re(models: dict, path: str | Path) -> None:
    np.savez_compressed(path, **{f"{k[0]}_{k[1]}": m.table for k, m in models.items()})
