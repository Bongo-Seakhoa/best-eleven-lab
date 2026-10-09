"""Opposition- and context-adjusted delivery values.

A ridge regression of per-ball contest value on batter, bowler, batting side,
bowling side and context (era x phase x innings x home) indicators separates
who you faced from how well you did. Player penalties are empirical-Bayes
estimates (noise variance over between-player variance), so a penalty equals
adding that many average balls to a player's record. Team effects are nearly
unpenalised: they carry the strength of a whole bowling unit or batting order,
which matters when a weak side's individual players are rarely seen elsewhere.

The adjusted value credited to a batter for one ball is the observed value
minus the fitted bowler, bowling-side and context effects; summing it over any
window gives an additive, opposition-adjusted total. Bowlers are symmetric.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import lsqr

TEAM_LAMBDA = 25.0
CTX_LAMBDA = 1.0


@dataclass
class AdjustFit:
    mu: float
    lam_bat: float
    lam_bowl: float
    coef: dict
    sigma2: float
    n: int


def eb_lambda(y: np.ndarray, groups: np.ndarray, min_n: int = 300) -> tuple[float, float]:
    """Empirical-Bayes ratio sigma^2 / tau^2 from per-group means."""
    df = pd.DataFrame({"y": y, "g": groups})
    s = df.groupby("g")["y"].agg(["mean", "var", "size"])
    s = s[s["size"] >= min_n]
    sigma2 = float(np.average(s["var"], weights=s["size"])) if len(s) else float(np.var(y))
    if len(s) < 10:
        return 400.0, sigma2
    between = float(np.var(s["mean"], ddof=1))
    noise = float(np.mean(sigma2 / s["size"]))
    tau2 = max(between - noise, sigma2 / 5000.0)
    return float(np.clip(sigma2 / tau2, 50.0, 5000.0)), sigma2


def fit(y: np.ndarray, factors: dict[str, np.ndarray]) -> AdjustFit:
    """factors: name -> integer codes; must include 'batter', 'bowler', 'bat_team',
    'bowl_team', 'ctx'. Each factor gets its own effective ridge penalty."""
    y = np.asarray(y, dtype=np.float64)
    lam_bat, sigma2 = eb_lambda(y, factors["batter"])
    lam_bowl, _ = eb_lambda(y, factors["bowler"])
    lams = {"batter": lam_bat, "bowler": lam_bowl, "bat_team": TEAM_LAMBDA,
            "bowl_team": TEAM_LAMBDA, "ctx": CTX_LAMBDA}
    mu = float(y.mean())
    n = len(y)
    rows, cols, vals, spans, offset = [], [], [], {}, 0
    for name, c in factors.items():
        k = int(c.max()) + 1
        scale = np.sqrt(lam_bat / lams[name])   # rescaled column => penalty lams[name]
        rows.append(np.arange(n)); cols.append(offset + c); vals.append(np.full(n, scale))
        spans[name] = (offset, k, scale)
        offset += k
    X = csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, offset))
    sol = lsqr(X, y - mu, damp=np.sqrt(lam_bat), atol=1e-7, btol=1e-7, iter_lim=500)[0]
    coef = {name: sol[o:o + k] * s for name, (o, k, s) in spans.items()}
    return AdjustFit(mu, lam_bat, lam_bowl, coef, sigma2, n)


def adjusted_values(y, factors: dict[str, np.ndarray], f: AdjustFit) -> tuple[np.ndarray, np.ndarray]:
    """Per-ball value credited to the batter and charged to the bowler, each net
    of the opposing player, the opposing side and the context."""
    c = f.coef
    base = f.mu + c["ctx"][factors["ctx"]]
    bat_adj = y - base - c["bowler"][factors["bowler"]] - c["bowl_team"][factors["bowl_team"]]
    bowl_adj = y - base - c["batter"][factors["batter"]] - c["bat_team"][factors["bat_team"]]
    return bat_adj.astype(np.float32), bowl_adj.astype(np.float32)


def codes(series: pd.Series) -> tuple[np.ndarray, int]:
    c = pd.Categorical(series)
    return c.codes.astype(np.int64), len(c.categories)
