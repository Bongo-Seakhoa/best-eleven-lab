"""Bowling archetypes.

Cricsheet does not record bowling styles. Wikipedia gives a style for roughly
half of the bowlers; for the rest, a gradient-boosted classifier trained on the
labelled bowlers predicts pace or spin from how they are used and how they take
wickets. Only confident predictions are kept, and every label carries its
source ('wikipedia' or 'model') so the site can show which is which.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from .frames import Warehouse

COLS = ["match_id", "inning", "over", "bowler", "legal", "phase", "wides", "noballs", "byes",
        "legbyes", "conceded", "bowler_wkt", "striker_kind", "fielder", "super_over"]
MIN_BALLS = 120
CONFIDENCE = 0.85
CLASS_LABELS = {"RF": "Right-arm fast", "RFM": "Right-arm fast-medium", "RMF": "Right-arm medium-fast",
                "RM": "Right-arm medium", "LF": "Left-arm fast", "LFM": "Left-arm fast-medium",
                "LMF": "Left-arm medium-fast", "LM": "Left-arm medium", "OB": "Off-spin",
                "LB": "Leg-spin", "SLA": "Left-arm orthodox", "LWS": "Left-arm wrist-spin"}
# Matchup groups used in profiles: arm and method, coarse enough to keep samples useful.
GROUPS = {"RF": "Right-arm pace", "RFM": "Right-arm pace", "RMF": "Right-arm pace", "RM": "Right-arm pace",
          "LF": "Left-arm pace", "LFM": "Left-arm pace", "LMF": "Left-arm pace", "LM": "Left-arm pace",
          "OB": "Off-spin", "LB": "Leg-spin", "SLA": "Left-arm orthodox", "LWS": "Left-arm wrist-spin"}


def bowler_features(wh: Warehouse, keepers: pd.DataFrame) -> pd.DataFrame:
    """Per-bowler usage and dismissal features pooled over every scope."""
    m = wh.matches[["match_id", "family"]]
    inn = wh.innings[["match_id", "inning", "bowling_team"]].astype({"bowling_team": str})
    kp = keepers.rename(columns={"team": "bowling_team", "keeper": "kid"})[["match_id", "bowling_team", "kid"]]
    parts = []
    for scope in wh.scopes():
        d = wh.deliveries(scope, COLS, with_context=False)
        d = d[d["super_over"] == 0].merge(m, on="match_id")
        d = d.merge(inn, on=["match_id", "inning"]).merge(kp, on=["match_id", "bowling_team"], how="left")
        lo = d["family"] != "multi"
        test = d["family"] == "multi"
        credit = d["bowler_wkt"] > 0
        f = pd.DataFrame({
            "bowler": d["bowler"], "balls": d["legal"],
            "lo_balls": d["legal"] * lo, "lo_pp": d["legal"] * lo * (d["phase"] == 0),
            "lo_death": d["legal"] * lo * (d["phase"] == 2),
            "t_balls": d["legal"] * test, "t_new": d["legal"] * test * (d["over"] < 15),
            "t_late": d["legal"] * test * (d["inning"] >= 3),
            "open": (d["over"] <= 1).astype(int) * d["legal"],
            "wides": (d["wides"] > 0).astype(int), "noballs": (d["noballs"] > 0).astype(int),
            "byes": (d["byes"] > 0).astype(int), "legbyes": (d["legbyes"] > 0).astype(int),
            "runs": d["conceded"], "wkts": d["bowler_wkt"],
            "w_keeper": (credit & (d["striker_kind"] == 1) & (d["fielder"] == d["kid"])).astype(int),
            "w_stumped": (credit & (d["striker_kind"] == 6)).astype(int),
            "w_bowled": (credit & (d["striker_kind"] == 2)).astype(int),
            "w_lbw": (credit & (d["striker_kind"] == 3)).astype(int),
            "w_cb": (credit & (d["striker_kind"] == 5)).astype(int),
            "w_field": (credit & (d["striker_kind"] == 1) & (d["fielder"] != d["kid"])).astype(int),
        })
        parts.append(f.groupby("bowler").sum())
        del d, f
    s = pd.concat(parts).groupby(level=0).sum()
    w = s["wkts"].clip(lower=1)
    X = pd.DataFrame(index=s.index)
    X["balls"] = s["balls"]
    X["lo_share"] = s["lo_balls"] / s["balls"].clip(lower=1)
    X["pp_share"] = (s["lo_pp"] / s["lo_balls"]).where(s["lo_balls"] >= 60)
    X["death_share"] = (s["lo_death"] / s["lo_balls"]).where(s["lo_balls"] >= 60)
    X["new_ball_share"] = (s["t_new"] / s["t_balls"]).where(s["t_balls"] >= 120)
    X["late_innings_share"] = (s["t_late"] / s["t_balls"]).where(s["t_balls"] >= 120)
    X["open_share"] = s["open"] / s["balls"].clip(lower=1)
    for c in ("wides", "noballs", "byes", "legbyes"):
        X[f"{c}_rate"] = s[c] / s["balls"].clip(lower=1)
    X["runs_per_ball"] = s["runs"] / s["balls"].clip(lower=1)
    X["wkt_rate"] = s["wkts"] / s["balls"].clip(lower=1)
    for c in ("w_keeper", "w_stumped", "w_bowled", "w_lbw", "w_cb", "w_field"):
        X[c + "_share"] = (s[c] / w).where(s["wkts"] >= 3)
    return X


def classify(features: pd.DataFrame, labels: pd.Series) -> tuple[pd.DataFrame, dict]:
    """Fit pace-vs-spin on labelled bowlers; predict the rest."""
    X = features[features["balls"] >= MIN_BALLS].drop(columns=["balls"])
    y = labels.reindex(X.index)
    train = y.isin(["pace", "spin"])
    Xt, yt = X[train], (y[train] == "spin").astype(int)
    model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                           l2_regularization=1.0, random_state=11)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=11)
    p_cv = cross_val_predict(model, Xt, yt, cv=cv, method="predict_proba")[:, 1]
    confident = (p_cv >= CONFIDENCE) | (p_cv <= 1 - CONFIDENCE)
    metrics = {
        "training_bowlers": int(len(yt)), "spin_share": round(float(yt.mean()), 3),
        "cv_accuracy": round(float(accuracy_score(yt, p_cv >= 0.5)), 4),
        "cv_auc": round(float(roc_auc_score(yt, p_cv)), 4),
        "cv_confident_coverage": round(float(confident.mean()), 4),
        "cv_confident_accuracy": round(float(accuracy_score(yt[confident], p_cv[confident] >= 0.5)), 4),
        "confidence_threshold": CONFIDENCE, "min_balls": MIN_BALLS,
    }
    model.fit(Xt, yt)
    unl = X[~train]
    p = model.predict_proba(unl)[:, 1] if len(unl) else np.array([])
    pred = pd.DataFrame({"p_spin": p}, index=unl.index)
    pred["family"] = np.where(pred["p_spin"] >= CONFIDENCE, "spin",
                              np.where(pred["p_spin"] <= 1 - CONFIDENCE, "pace", ""))
    metrics["predicted"] = int((pred["family"] != "").sum())
    metrics["unresolved"] = int((pred["family"] == "").sum())
    return pred, metrics


def build_bowler_families(warehouse: str | Path, model_dir: str | Path, reference: str | Path) -> dict:
    wh = Warehouse(warehouse)
    model_dir = Path(model_dir)
    keepers = pd.read_parquet(model_dir / "keepers.parquet")
    feats = bowler_features(wh, keepers)
    wiki_path = Path(reference) / "players_wiki.csv"
    ids = wh.players.set_index("player")["id"]
    labels = pd.Series("", index=feats.index)
    if wiki_path.exists():
        w = pd.read_csv(wiki_path, dtype=str, keep_default_na=False)
        fam = w[w["cricsheet_id"] != ""].drop_duplicates("cricsheet_id").set_index("cricsheet_id")["bowling_family"]
        labels = ids.reindex(feats.index).map(fam).fillna("")
    pred, metrics = classify(feats, labels)
    out = pred.reset_index().rename(columns={"index": "player", "bowler": "player"})
    out.to_parquet(model_dir / "bowler_family.parquet", index=False)
    (model_dir / "bowler_family_metrics.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    return metrics
