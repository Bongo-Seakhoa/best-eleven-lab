"""Priors for short records: what a player's cricket elsewhere predicts here.

A rating shrinks a short record towards a prior. Without one, the prior is the
average Full-Member player (zero), which flatters fringe players and undersells
a league star in his first internationals. Here the prior for each international
format comes from the player's own record in the other formats and in leagues,
through transitions measured on players who have played both.

Units are the model's adjusted runs per ball: batting runs added (ba / b) and
bowling runs saved (-wc / wb), each in its own fit group's scale. Sources for a
target format are the other international formats of the same gender and that
gender's leagues taken together (one fit group, one scale).

For a target T and source S, over players with at least MIN_BALLS in both:

    target rate = alpha + beta * (source rate shrunk with the source's lambda)

fitted by weighted least squares, each player weighted by the reliability of his
target rate, b / (b + lambda_T). The newcomer baseline is the ball-weighted mean
rate of players in their first season of the target format; its spread is the
same weighted variance of established players around it. A player's prior is the
precision-weighted mean of the baseline and his sources' predictions (weight:
source reliability / residual variance), so a thin record elsewhere moves him
only a little from the baseline and a long one moves him a lot.

`build_priors` uses every season. `debut_check` refits on seasons before a split
year and scores debutants after it from what they had done before their debut,
against the zero prior and the newcomer baseline, so the gain is measured on
players the fit never saw.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

INTERNATIONAL = {
    "male": ["men-test", "men-odi", "men-t20i"],
    "female": ["women-test", "women-odi", "women-t20i"],
}
CLUB = {"male": "men-club", "female": "women-club"}
MIN_BALLS = {"bat": 300, "bowl": 300}
MIN_PAIRS = 25
COLS = {"bat": ("ba", "b"), "bowl": ("wc", "wb")}


def _sign(kind: str) -> float:
    return -1.0 if kind == "bowl" else 1.0      # bowling value is runs saved = -cost


def load_units(model_dir: Path, scopes: dict[str, dict]) -> dict[str, pd.DataFrame]:
    """Season rows per rating unit: each international scope, and each gender's leagues together.

    scopes: scope key -> {"tier", "gender"} (from the site's scope metadata).
    """
    units: dict[str, list[pd.DataFrame]] = {}
    for key, meta in scopes.items():
        path = Path(model_dir) / "seasons" / f"{key}.parquet"
        if not path.exists():
            continue
        d = pd.read_parquet(path, columns=["player", "year", "m", "b", "ba", "wb", "wc"])
        unit = key if meta["tier"] == "national" else CLUB[meta["gender"]]
        units.setdefault(unit, []).append(d)
    return {u: pd.concat(parts, ignore_index=True) for u, parts in units.items()}


def career(units: dict[str, pd.DataFrame], before: int | None = None) -> dict[str, pd.DataFrame]:
    """Per unit and player: summed balls and values, optionally from seasons before a year."""
    out = {}
    for unit, d in units.items():
        if before is not None:
            d = d[d["year"] < before]
        out[unit] = d.groupby("player")[["m", "b", "ba", "wb", "wc"]].sum()
    return out


PART_TIME_BALLS_PER_MATCH = 6.0


def part_time_rate(car: dict[str, pd.DataFrame], unit: str) -> float | None:
    """Runs saved per ball by occasional bowlers: players who average an over a match
    or less (and have bowled at least 30 balls). An eleven short of bowlers pays this."""
    c = car.get(unit)
    if c is None:
        return None
    c = c[(c["wb"] >= 30) & (c["wb"] <= PART_TIME_BALLS_PER_MATCH * c["m"])]
    return float(-c["wc"].sum() / c["wb"].sum()) if c["wb"].sum() > 0 else None


def _rate(c: pd.DataFrame, kind: str, lam: float | None = None) -> pd.Series:
    val, balls = COLS[kind]
    denom = c[balls] + (lam or 0.0)
    return _sign(kind) * c[val] / denom.where(denom > 0)


def newcomer_baseline(units: dict[str, pd.DataFrame], unit: str, kind: str, before: int | None = None) -> float:
    d = units[unit]
    if before is not None:
        d = d[d["year"] < before]
    first = d.groupby("player")["year"].transform("min")
    d = d[d["year"] == first]
    val, balls = COLS[kind]
    b = d[balls].sum()
    return float(_sign(kind) * d[val].sum() / b) if b > 0 else 0.0


def baseline_var(car: dict[str, pd.DataFrame], unit: str, kind: str, base: float, lam_t: float) -> float:
    """Weighted spread of established players around the baseline (the baseline's own residual variance)."""
    val, balls = COLS[kind]
    c = car[unit]
    c = c[c[balls] >= MIN_BALLS[kind]]
    if c.empty:
        return 1.0
    y = _sign(kind) * c[val] / c[balls]
    w = c[balls] / (c[balls] + lam_t)
    return max(float(np.sum(w * (y - base) ** 2) / np.sum(w)), 1e-6)


def fit_transfers(car: dict[str, pd.DataFrame], target: str, sources: list[str], kind: str,
                  lam: dict[str, float]) -> dict[str, dict]:
    """alpha, beta and residual variance of target rate on each source's shrunk rate."""
    val, balls = COLS[kind]
    t = car[target]
    fits = {}
    for s in sources:
        if s not in car:
            continue
        j = t.join(car[s], lsuffix="_t", rsuffix="_s", how="inner")
        j = j[(j[f"{balls}_t"] >= MIN_BALLS[kind]) & (j[f"{balls}_s"] >= MIN_BALLS[kind])]
        if len(j) < MIN_PAIRS:
            continue
        y = _sign(kind) * j[f"{val}_t"] / j[f"{balls}_t"]
        x = _sign(kind) * j[f"{val}_s"] / (j[f"{balls}_s"] + lam[s])
        w = j[f"{balls}_t"] / (j[f"{balls}_t"] + lam[target])
        X = np.column_stack([np.ones(len(x)), x.to_numpy()])
        W = w.to_numpy()
        beta = np.linalg.lstsq(X * np.sqrt(W)[:, None], y.to_numpy() * np.sqrt(W), rcond=None)[0]
        resid = y.to_numpy() - X @ beta
        var = float(np.sum(W * resid ** 2) / np.sum(W))
        # Correlation between prediction and target, ball-weighted, for the record.
        pred = X @ beta
        r = float(np.corrcoef(pred, y.to_numpy())[0, 1]) if len(y) > 2 else 0.0
        fits[s] = {"alpha": float(beta[0]), "beta": float(beta[1]), "resid_var": max(var, 1e-6),
                   "n": int(len(j)), "r": round(r, 3)}
    return fits


def predict(car: dict[str, pd.DataFrame], fits: dict[str, dict], kind: str, lam: dict[str, float],
            baseline: float, base_var: float, players: pd.Index | None = None) -> pd.Series:
    """Prior per player: the baseline and his sources' predictions, precision-weighted."""
    val, balls = COLS[kind]
    num, den = None, None
    for s, f in fits.items():
        c = car[s]
        x = _sign(kind) * c[val] / (c[balls] + lam[s])
        rel = c[balls] / (c[balls] + lam[s])
        w = rel / f["resid_var"]
        p = f["alpha"] + f["beta"] * x
        num = (w * p) if num is None else num.add(w * p, fill_value=0.0)
        den = w if den is None else den.add(w, fill_value=0.0)
    w0 = 1.0 / base_var
    if num is None:
        prior = pd.Series(dtype=float)
    else:
        prior = ((num + w0 * baseline) / (den + w0)).dropna()
    if players is not None:
        prior = prior.reindex(players)
    return prior.fillna(baseline)


def build_priors(model_dir: Path, scopes: dict[str, dict], lam: dict[str, dict]) -> dict:
    """Priors per international unit for every player with data anywhere of that gender.

    lam: unit -> {"bat": lambda, "bowl": lambda}.
    Returns {"targets": {unit: {kind: {"baseline", "fits"}}}, "players": {unit: {kind: Series}}}.
    """
    units = load_units(model_dir, scopes)
    car = career(units)
    out = {"targets": {}, "players": {}, "partTime": {u: part_time_rate(car, u) for u in car}}
    for gender, targets in INTERNATIONAL.items():
        everyone = pd.Index(sorted(set().union(*[set(car[u].index) for u in car
                                                 if u in targets or u == CLUB[gender]])))
        for t in targets:
            if t not in car:
                continue
            sources = [u for u in targets if u != t] + [CLUB[gender]]
            out["targets"][t], out["players"][t] = {}, {}
            for kind in ("bat", "bowl"):
                lk = {u: lam[u][kind] for u in lam}
                fits = fit_transfers(car, t, sources, kind, lk)
                base = newcomer_baseline(units, t, kind)
                bvar = baseline_var(car, t, kind, base, lk[t])
                out["targets"][t][kind] = {"baseline": base, "baseline_var": bvar, "fits": fits}
                out["players"][t][kind] = predict(car, fits, kind, lk, base, bvar, everyone)
    return out


def debut_check(model_dir: Path, scopes: dict[str, dict], lam: dict[str, dict], split: int = 2019,
                eval_seasons: int = 2, min_eval_balls: int = 150) -> dict:
    """Score priors on players who debuted in a format from `split` on.

    Transfers are fitted on seasons before `split`. Each debutant's prior uses
    only seasons before his debut year. The outcome is his raw rate over his
    first `eval_seasons` seasons in the format (at least `min_eval_balls`).
    Error is ball-weighted mean squared error against the zero prior and the
    newcomer baseline.
    """
    units = load_units(model_dir, scopes)
    early = career(units, before=split)
    report = {}
    for gender, targets in INTERNATIONAL.items():
        for t in targets:
            if t not in units:
                continue
            d = units[t]
            first = d.groupby("player")["year"].min()
            debut = first[first >= split]
            sources = [u for u in targets if u != t] + [CLUB[gender]]
            report[t] = {}
            for kind in ("bat", "bowl"):
                val, balls = COLS[kind]
                lk = {u: lam[u][kind] for u in lam}
                fits = fit_transfers(early, t, sources, kind, lk)
                base = newcomer_baseline(units, t, kind, before=split)
                bvar = baseline_var(early, t, kind, base, lk[t]) if t in early else 1.0
                rows = []
                for year, ids in debut.groupby(debut):
                    before = career(units, before=int(year))
                    prior = predict(before, fits, kind, lk, base, bvar, pd.Index(ids.index))
                    window = d[d["player"].isin(ids.index) & (d["year"] >= year) & (d["year"] < year + eval_seasons)]
                    g = window.groupby("player")[[val, balls]].sum()
                    g = g[g[balls] >= min_eval_balls]
                    for pid, row in g.iterrows():
                        rows.append((float(_sign(kind) * row[val] / row[balls]), float(row[balls]), float(prior.get(pid, base))))
                if len(rows) < MIN_PAIRS:
                    report[t][kind] = {"players": len(rows), "judged": False, "fits": len(fits)}
                    continue
                y, w, p = (np.array(c) for c in zip(*rows))
                mse = lambda pred: float(np.sum(w * (y - pred) ** 2) / np.sum(w))
                report[t][kind] = {
                    "players": len(rows), "judged": True, "fits": len(fits),
                    "mse_prior": mse(p), "mse_zero": mse(np.zeros_like(y)), "mse_newcomer": mse(np.full_like(y, base)),
                }
    return report


def scope_info(warehouse: Path) -> dict[str, dict]:
    """scope -> {"tier", "gender"} from the warehouse's match table."""
    m = pd.read_parquet(Path(warehouse) / "matches.parquet", columns=["scope", "team_type", "gender"])
    m = m.drop_duplicates("scope")
    return {str(r.scope): {"tier": "national" if r.team_type == "international" else "league", "gender": str(r.gender)}
            for r in m.itertuples()}


def lambdas(model_dir: Path) -> dict[str, dict]:
    import json
    groups = json.loads((Path(model_dir) / "values_summary.json").read_text(encoding="utf-8"))["groups"]
    return {u: {"bat": float(v["lambda_bat"]), "bowl": float(v["lambda_bowl"])} for u, v in groups.items()}


def site_priors(warehouse: Path, model_dir: Path) -> dict:
    """Everything the site needs: per-unit fits and baselines, and each player's prior per unit."""
    return build_priors(Path(model_dir), scope_info(warehouse), lambdas(model_dir))


def debut_validation(warehouse: Path, model_dir: Path, split: int = 2019) -> dict:
    """The build check: on debutants from `split` on, the prior must beat the zero prior."""
    rep = debut_check(Path(model_dir), scope_info(warehouse), lambdas(model_dir), split=split)
    judged = [(t, k, v) for t, kinds in rep.items() for k, v in kinds.items() if v.get("judged")]
    better = [v["mse_prior"] < v["mse_zero"] for _, _, v in judged]
    parts = [f"{t} {k}: {v['mse_prior']:.3f} vs {v['mse_zero']:.3f} ({v['players']} debutants)" for t, k, v in judged]
    unjudged = [f"{t} {k}" for t, kinds in rep.items() for k, v in kinds.items() if not v.get("judged")]
    summary = "Weighted squared error, prior vs average-player prior: " + "; ".join(parts)
    if unjudged:
        summary += f". Too few debutants to judge: {', '.join(unjudged)}"
    return {"name": "Debut priors: newcomers' first seasons predicted better than by an average player",
            "passed": bool(judged) and all(better), "summary": summary, "split_year": split, "targets": rep}
