"""Calibrate XI vs XI win chances against real matches.

Every completed match in an exported scope (internationals between ICC Full
Members; every league match) becomes two real elevens. The site's own engine
(site/cli/versus-calibrate.mjs) rates each player from that scope's seasons in
the WINDOW years before the match and projects the edge in runs per match. A
win-chance curve is then fitted per (tier, gender, family):

  limited overs  P(A wins) = sigmoid(k * edge), no intercept
  Tests          ordered logit: P(A wins) = sigmoid(k * edge - c),
                 P(B wins) = sigmoid(-k * edge - c), the draw takes the rest

Fits use matches up to SPLIT_YEAR; later matches are held out to measure Brier
score and log loss against a naive forecast. A home-side term is fitted
alongside k so that home advantage does not leak into it; the stored k and c
are the neutral-venue parameters the site uses.

A group is calibrated only when its training years already show the curve
travels: each of the last FORWARD_YEARS training seasons is predicted from a
fit on the seasons before it, and those forecasts together must beat the naive
one on Brier score. The held-out years play no part in that decision, so the
held-out comparison stays a genuine test. A group that fails is left without
win chances rather than given numbers that are no better than a guess.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .context import home_teams
from .values import FULL_MEMBERS

WINDOW = 4          # seasons Y-4..Y-1 rate a player for a match in year Y
HALF_LIFE = 3
SPLIT_YEAR = 2020   # fit on matches up to here, evaluate on later ones
MIN_RATED = 6       # players per side with a record in the window
MIN_TRAIN = 150
MIN_TEST = 50
FORWARD_YEARS = 3   # training seasons forecast one at a time by the gate
FORWARD_MIN_FIT = 50
FORWARD_MIN_N = 30

FAMILY_LABEL = {"national": {"multi": "Tests", "fifty": "ODIs", "t20": "T20Is", "hundred": "Hundred"},
                "league": {"multi": "first-class", "fifty": "one-day leagues", "t20": "T20 leagues",
                           "hundred": "Hundred"}}


def group_label(key: str) -> str:
    tier, gender, family = key.split(":")
    return f"{'Men' if gender == 'male' else 'Women'}'s {FAMILY_LABEL[tier][family]}"


# ---------------------------------------------------------------------------
# Matches


def match_list(warehouse: str | Path, scopes: list[str]) -> tuple[pd.DataFrame, dict]:
    """Completed, full-length matches in the given scopes with both elevens.

    Returns one row per match (team1 is side A) with the outcome for side A
    (limited overs: 1 win, 0.5 tie, 0 loss; Tests: 2 win, 1 draw, 0 loss), the
    home indicator (+1 side A at home, -1 side B, 0 neutral) and both sides in
    batting order, plus counts of what was skipped and why.
    """
    wh = Path(warehouse)
    allm = pd.read_parquet(wh / "matches.parquet")
    m = allm[allm["scope"].isin(scopes)].copy()
    skipped = {}

    def drop(mask, reason):
        nonlocal m
        if mask.any():
            skipped[reason] = skipped.get(reason, 0) + int(mask.sum())
        m = m[~mask]

    intl = m["team_type"] == "international"
    drop(intl & ~(m["team1"].isin(FULL_MEMBERS) & m["team2"].isin(FULL_MEMBERS)), "not between Full Members")
    drop(m["result"] == "no result", "no result")
    drop(m["method"].fillna("") != "", "decided by a rain rule or awarded")
    limited = m["family"] != "multi"
    drop(limited & (m["result"] == "tie") & (m["eliminator"].fillna("") != ""), "tie settled by a super over")
    inn = pd.read_parquet(wh / "innings.parquet",
                          columns=["match_id", "inning", "batting_team", "super_over", "max_balls"])
    inn = inn[(inn["super_over"] == 0) & inn["match_id"].isin(m["match_id"])]
    full = (m["overs"] * m["bpo"]).set_axis(m["match_id"])
    short = inn[(inn["max_balls"] >= 0) & (inn["max_balls"] < inn["match_id"].map(full))]["match_id"]
    drop((m["family"] != "multi") & m["match_id"].isin(short), "overs reduced")

    tests = m["family"] == "multi"
    a_won, b_won = m["winner"] == m["team1"], m["winner"] == m["team2"]
    m["outcome"] = np.where(tests, np.where(a_won, 2.0, np.where(b_won, 0.0, 1.0)),
                            np.where(a_won, 1.0, np.where(b_won, 0.0, 0.5)))
    undecided = (m["result"] == "win") & ~a_won & ~b_won
    drop(undecided, "winner not recorded")

    home = home_teams(allm).set_index("match_id")["home_team"]
    h = m["match_id"].map(home)
    m["home"] = np.where(h == m["team1"], 1, np.where(h == m["team2"], -1, 0))

    sides = _batting_orders(wh, m["match_id"])
    m["a"] = [sides.get((mid, t), []) for mid, t in zip(m["match_id"], m["team1"])]
    m["b"] = [sides.get((mid, t), []) for mid, t in zip(m["match_id"], m["team2"])]
    drop((m["a"].map(len) < 11) | (m["b"].map(len) < 11), "eleven not recorded")
    return m.reset_index(drop=True), skipped


def _batting_orders(wh: Path, match_ids: pd.Series) -> dict:
    """(match_id, team) -> Cricsheet ids: batting order in the side's first
    innings, then everyone else in the order the team sheet lists them."""
    ids = pd.read_parquet(wh / "players.parquet", columns=["player", "id"]).set_index("player")["id"]
    keep = set(match_ids)
    app = pd.read_parquet(wh / "appearances.parquet", columns=["match_id", "team", "player"])
    app = app[app["match_id"].isin(keep)].astype({"team": str})
    app["sheet"] = np.arange(len(app))
    bat = pd.read_parquet(wh / "batting.parquet", columns=["match_id", "inning", "team", "player", "position",
                                                          "super_over"])
    bat = bat[bat["match_id"].isin(keep) & (bat["super_over"] == 0)].astype({"team": str})
    first = bat.groupby(["match_id", "team"])["inning"].transform("min")
    bat = bat[bat["inning"] == first].drop_duplicates(["match_id", "team", "player"])
    app = app.merge(bat[["match_id", "team", "player", "position"]], on=["match_id", "team", "player"], how="left")
    app["order"] = app["position"].fillna(99)
    app = app.sort_values(["match_id", "team", "order", "sheet"])
    app["cid"] = app["player"].map(ids)
    return {key: g.tolist() for key, g in app.groupby(["match_id", "team"], sort=False)["cid"]}


# ---------------------------------------------------------------------------
# The engine


def project_edges(matches: pd.DataFrame, scopes_dir: Path, groups: dict, script: Path, node: str) -> pd.DataFrame:
    """Run the site engine on every match; returns id, key, edge, scoreA, scoreB, rated_a, rated_b."""
    payload = {"scopesDir": str(scopes_dir), "groups": groups, "window": WINDOW, "halfLife": HALF_LIFE,
               "matches": [{"id": int(r.match_id), "scope": r.scope, "year": int(r.year), "a": r.a, "b": r.b}
                           for r in matches.itertuples()]}
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "matches.json", Path(tmp) / "edges.json"
        src.write_text(json.dumps(payload), encoding="utf-8")
        run = subprocess.run([node, str(script), str(src), str(dst)], capture_output=True, text=True)
        if run.returncode:
            raise RuntimeError(f"XI vs XI engine failed: {(run.stderr or run.stdout).strip()[-800:]}")
        rows = json.loads(dst.read_text(encoding="utf-8"))
    out = pd.DataFrame(rows)
    if len(out) != len(matches):
        raise RuntimeError(f"XI vs XI engine returned {len(out)} edges for {len(matches)} matches")
    out[["rated_a", "rated_b"]] = pd.DataFrame(out.pop("rated").tolist(), index=out.index)
    return out.rename(columns={"id": "match_id"})


# ---------------------------------------------------------------------------
# Fitting


def _log_sigmoid(z):
    return -np.logaddexp(0.0, -z)


def _scale(edge: np.ndarray) -> float:
    s = float(np.std(edge))
    return s if s > 0 else 1.0


def _converged(res, n: int, what: str):
    # BFGS may stop on precision loss at the optimum; the gradient per match decides.
    if not np.isfinite(res.fun) or np.max(np.abs(res.jac)) > 1e-4 * max(n, 1):
        raise RuntimeError(f"{what} fit did not converge: {res.message}")


def fit_logistic(edge, y, home=None) -> dict:
    """P(A wins) = sigmoid(k * edge + h * home); y in [0, 1] (a tie is 0.5)."""
    edge, y = np.asarray(edge, float), np.asarray(y, float)
    home = np.zeros_like(edge) if home is None else np.asarray(home, float)
    s = _scale(edge)
    x = edge / s

    def nll(t):
        z = t[0] * x + t[1] * home
        return -np.sum(y * _log_sigmoid(z) + (1 - y) * _log_sigmoid(-z))

    def grad(t):
        z = t[0] * x + t[1] * home
        r = y - 1 / (1 + np.exp(-z))
        return -np.array([np.sum(r * x), np.sum(r * home)])

    res = minimize(nll, np.zeros(2), jac=grad, method="BFGS")
    _converged(res, len(edge), "logistic")
    return {"k": float(res.x[0] / s), "home": float(res.x[1])}


def ordered_probs(edge, k: float, c: float, home=None, h: float = 0.0) -> np.ndarray:
    """Columns: P(B wins), P(draw), P(A wins)."""
    z = k * np.asarray(edge, float) + (0.0 if home is None else h * np.asarray(home, float))
    pa = 1 / (1 + np.exp(-(z - c)))
    pb = 1 / (1 + np.exp(z + c))
    return np.column_stack([pb, np.clip(1 - pa - pb, 0, 1), pa])


def fit_ordered(edge, outcome, home=None) -> dict:
    """Ordered logit with cutpoints at -c and +c; outcome 0 B wins, 1 draw, 2 A wins."""
    edge, o = np.asarray(edge, float), np.asarray(outcome).astype(int)
    home = np.zeros_like(edge) if home is None else np.asarray(home, float)
    s = _scale(edge)
    x = edge / s

    def nll(t):
        k, logc, h = t
        c = np.exp(logc)
        z = k * x + h * home
        lp_a = _log_sigmoid(z - c)
        lp_b = _log_sigmoid(-z - c)
        # sigmoid(z + c) - sigmoid(z - c), kept stable in the tails
        lp_d = _log_sigmoid(z + c) + _log_sigmoid(-(z - c)) + np.log(-np.expm1(-2 * c))
        return -np.sum(np.where(o == 2, lp_a, np.where(o == 0, lp_b, lp_d)))

    res = minimize(nll, np.array([0.0, 0.0, 0.0]), method="BFGS")
    _converged(res, len(edge), "ordered")
    return {"k": float(res.x[0] / s), "c": float(np.exp(res.x[1])), "home": float(res.x[2])}


# ---------------------------------------------------------------------------
# Held-out evaluation


def _bins(p_fav: np.ndarray, columns: dict, n_bins: int, floor: float) -> list[dict]:
    """Equal-count bins of the favoured side's predicted win chance. Bins meet
    halfway between neighbours and span [floor, 1], so any chance falls in one."""
    if len(p_fav) == 0:
        return []
    order = np.argsort(p_fav, kind="stable")
    chunks = [c for c in np.array_split(order, min(n_bins, len(order))) if len(c)]
    cuts = [(p_fav[a].max() + p_fav[b].min()) / 2 for a, b in zip(chunks, chunks[1:])]
    edges = [floor, *cuts, 1.0]
    out = []
    for i, chunk in enumerate(chunks):
        row = {"lo": round(float(edges[i]), 3), "hi": round(float(edges[i + 1]), 3), "n": int(len(chunk))}
        for name, v in columns.items():
            row[name] = round(float(np.mean(v[chunk])), 3)
        out.append(row)
    return out


def evaluate_binary(edge, y, k: float) -> dict:
    edge, y = np.asarray(edge, float), np.asarray(y, float)
    p = np.clip(1 / (1 + np.exp(-k * edge)), 1e-12, 1 - 1e-12)
    decisive = (y != 0.5) & (edge != 0)
    fav_a = edge >= 0
    p_fav = np.where(fav_a, p, 1 - p)
    y_fav = np.where(fav_a, y, 1 - y)
    return {
        "brier": float(np.mean((p - y) ** 2)),
        "brierBaseline": float(np.mean((0.5 - y) ** 2)),
        "logLoss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        "logLossBaseline": float(np.log(2)),
        "accuracy": float(np.mean((edge[decisive] > 0) == (y[decisive] == 1))) if decisive.any() else None,
        "decisive": int(decisive.sum()),
        "bins": _bins(p_fav, {"predicted": p_fav, "observed": y_fav}, 10 if len(edge) >= 1000 else 5, 0.5),
    }


def evaluate_ordered(edge, outcome, k: float, c: float, p_draw: float) -> dict:
    edge, o = np.asarray(edge, float), np.asarray(outcome).astype(int)
    P = np.clip(ordered_probs(edge, k, c), 1e-12, 1)
    onehot = np.eye(3)[o]
    base = np.array([(1 - p_draw) / 2, p_draw, (1 - p_draw) / 2])
    decisive = (o != 1) & (edge != 0)
    fav_a = edge >= 0
    p_fav = np.where(fav_a, P[:, 2], P[:, 0])
    won_fav = np.where(fav_a, o == 2, o == 0).astype(float)
    return {
        "brier": float(np.mean(np.sum((P - onehot) ** 2, axis=1))),
        "brierBaseline": float(np.mean(np.sum((base - onehot) ** 2, axis=1))),
        "logLoss": float(-np.mean(np.log(P[np.arange(len(o)), o]))),
        "logLossBaseline": float(-np.mean(np.log(base[o]))),
        "accuracy": float(np.mean((edge[decisive] > 0) == (o[decisive] == 2))) if decisive.any() else None,
        "decisive": int(decisive.sum()),
        "bins": _bins(p_fav, {"predicted": p_fav, "observed": won_fav,
                              "predictedDraw": P[:, 1], "observedDraw": (o == 1).astype(float)},
                      10 if len(edge) >= 1000 else 5, 1 / (1 + np.exp(c))),  # level sides: sigmoid(-c)
    }


def _fit_eval(fit: pd.DataFrame, held: pd.DataFrame, tests: bool) -> tuple[dict, dict]:
    if tests:
        f = fit_ordered(fit["edge"], fit["outcome"], fit["home"])
        p_draw = float(np.mean(fit["outcome"] == 1))
        params = {"model": "ordered", "k": f["k"], "c": f["c"], "home": f["home"], "baselineDraw": p_draw}
        return params, evaluate_ordered(held["edge"], held["outcome"], f["k"], f["c"], p_draw)
    f = fit_logistic(fit["edge"], fit["outcome"], fit["home"])
    return {"model": "logistic", "k": f["k"], "home": f["home"]}, evaluate_binary(held["edge"], held["outcome"], f["k"])


def forward_check(train: pd.DataFrame, tests: bool) -> dict:
    """Forecast each of the last FORWARD_YEARS training seasons from a fit on the
    seasons before it; pooled Brier score against the naive forecast."""
    n = brier = base = 0.0
    years = []
    for t in sorted(train["year"].unique())[-FORWARD_YEARS:]:
        fit, held = train[train["year"] < t], train[train["year"] == t]
        if len(fit) < FORWARD_MIN_FIT or held.empty:
            continue
        _, ev = _fit_eval(fit, held, tests)
        n += len(held)
        brier += ev["brier"] * len(held)
        base += ev["brierBaseline"] * len(held)
        years.append(int(t))
    if n < FORWARD_MIN_N:
        return {"years": years, "n": int(n), "passed": False}
    return {"years": years, "n": int(n), "brier": brier / n, "brierBaseline": base / n,
            "passed": bool(brier < base)}


def fit_group(d: pd.DataFrame, tests: bool) -> dict:
    """Fit on d[train], evaluate on d[~train]; d has edge, outcome, home, year, train."""
    tr, te = d[d["train"]], d[~d["train"]]
    row, ev = _fit_eval(tr, te, tests)
    row["homeRuns"] = row["home"] / row["k"] if row["k"] > 0 else None
    row |= {"nTrain": int(len(tr)), "nTest": int(len(te)),
            "years": [int(d["year"].min()), int(d["year"].max())],
            "trainYears": [int(tr["year"].min()), int(tr["year"].max())],
            "testYears": [int(te["year"].min()), int(te["year"].max())] if len(te) else None,
            "edgeSd": float(np.std(d["edge"]))}
    row |= ev
    row["beatsBaseline"] = bool(ev["brier"] < ev["brierBaseline"])
    row["forward"] = forward_check(tr, tests)
    return row


def _round(x, key: str = ""):
    if isinstance(x, dict):
        return {k: _round(v, k) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v, key) for v in x]
    if isinstance(x, float):
        return round(x, {"k": 6, "homeRuns": 1, "edgeSd": 2}.get(key, 4))
    return x


def calibrate_versus(warehouse: str | Path, site_data: str | Path, script: str | Path, node: str,
                     *, log=print) -> dict:
    """Returns {"calibration": {groupKey: fit}, "method": settings, skipped matches and groups}."""
    site_data = Path(site_data)
    scopes_dir = site_data / "scopes"
    scopes = sorted(p.stem for p in scopes_dir.glob("*.json"))
    if not scopes:
        raise RuntimeError(f"no exported scopes in {scopes_dir}; run export first")
    groups = json.loads((site_data / "model" / "versus.json").read_text(encoding="utf-8"))["groups"]
    matches, skipped = match_list(warehouse, scopes)
    edges = project_edges(matches, scopes_dir, groups, Path(script), node)
    d = matches.merge(edges, on="match_id", validate="one_to_one")
    thin = (d["rated_a"] < MIN_RATED) | (d["rated_b"] < MIN_RATED)
    skipped[f"fewer than {MIN_RATED} rated players in a side"] = int(thin.sum())
    d = d[~thin].copy()
    d["train"] = d["year"] <= SPLIT_YEAR
    log(f"  {len(d):,} matches projected; skipped {skipped}")
    out, left_out = {}, {}
    for key in sorted(set(edges["key"])):
        g = d[d["key"] == key]
        n_tr, n_te = int(g["train"].sum()), int((~g["train"]).sum())
        label = group_label(key)
        if n_tr < MIN_TRAIN or n_te < MIN_TEST:
            left_out[key] = {"label": label, "nTrain": n_tr, "nTest": n_te,
                             "reason": f"fewer than {MIN_TRAIN} matches up to {SPLIT_YEAR} "
                                       f"or {MIN_TEST} after it"}
            log(f"  {key}: not calibrated ({n_tr} training, {n_te} held-out matches)")
            continue
        row = _round(fit_group(g, tests=key.endswith(":multi")))
        fw = row["forward"]
        if not fw["passed"]:
            why = (f"forecasts of {fw['years'][0]}-{fw['years'][-1]} from earlier seasons scored "
                   f"Brier {fw['brier']:.4f} against {fw['brierBaseline']:.4f} for the naive forecast"
                   if "brier" in fw else "too few training seasons to test forecasts")
            left_out[key] = {"label": label, "nTrain": n_tr, "nTest": n_te, "reason": why, "forward": fw,
                             "heldOut": {"brier": row["brier"], "brierBaseline": row["brierBaseline"]}}
            log(f"  {key}: not calibrated ({why})")
            continue
        out[key] = {"label": label, **row}
        cut = f", c {row['c']:.3f}" if "c" in row else ""
        log(f"  {key}: k {row['k']:.5f}{cut}, Brier {row['brier']:.4f} vs {row['brierBaseline']:.4f} "
            f"on {n_te} held out")
    method = {"window": WINDOW, "halfLife": HALF_LIFE, "splitYear": SPLIT_YEAR, "minRated": MIN_RATED,
              "minTrain": MIN_TRAIN, "minTest": MIN_TEST, "forwardYears": FORWARD_YEARS,
              "skippedMatches": skipped, "notCalibrated": left_out}
    return {"calibration": out, "method": method}
