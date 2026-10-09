"""Write the static site's data files (site/data/*.json).

Scope files are columnar: parallel arrays keep a 4,000-player T20I pool to a
few hundred kilobytes once GitHub Pages compresses them.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .model.frames import Warehouse
from .model.playerdb import INTL_SCOPES, PACE, SPIN, build_player_db, scope_flags

SCOPE_LABELS = {"men-test": "Men's Tests", "men-odi": "Men's ODIs", "men-t20i": "Men's T20Is",
                "women-test": "Women's Tests", "women-odi": "Women's ODIs", "women-t20i": "Women's T20Is"}
SEASON_RENAME = {"player": "p", "year": "y", "team": "t", "opp_full": "o", "o": "out"}
FLOAT_COLS = {"ba", "wc"}


def _clean(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if not math.isfinite(float(v)) else round(float(v), 2)
    return v


def dump(obj, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_clean)
    path.write_text(text, encoding="utf-8")
    return len(text)


def scope_meta(scope: str, wh: Warehouse, leagues: dict, groups: dict) -> dict:
    m = wh.matches[wh.matches["scope"] == scope]
    fam = m["family"].mode().iat[0]
    if scope in INTL_SCOPES:
        gender, fmt = INTL_SCOPES[scope]
        tier, label, group = "national", SCOPE_LABELS[scope], scope
        extra = {}
    else:
        lg = leagues[scope]
        gender, fmt, tier, label = lg["gender"], "T20" if fam != "hundred" else "Hundred", "league", lg["label"]
        group = "men-club" if gender == "male" else "women-club"
        extra = {"short": lg["short"], "host": lg["host"], "featured": lg["featured"],
                 "maxOverseas": lg.get("max_overseas"), "overseasSource": lg.get("overseas_source", "")}
    g = groups.get(group, {})
    return {"key": scope, "label": label, "tier": tier, "gender": gender, "format": fmt, "family": fam,
            "years": [int(m["year"].min()), int(m["year"].max())], "matches": int(len(m)),
            "lambda": {"bat": g.get("lambda_bat", 400.0), "bowl": g.get("lambda_bowl", 400.0)},
            "adjusted": bool(g.get("adjusted", False)), "fitGroup": group, **extra}


def export_scope(scope: str, seasons: pd.DataFrame, ctx: dict, meta: dict, out: Path,
                 inferred_fam: pd.Series | None = None) -> dict:
    db = ctx["db"]
    players = pd.Index(sorted(seasons["player"].unique()))
    local = pd.Series(np.arange(len(players)), index=players)
    teams = sorted(seasons["team"].astype(str).unique())
    tmap = {t: i for i, t in enumerate(teams)}
    flags = scope_flags(ctx, scope, players, seasons)
    s = seasons.rename(columns=SEASON_RENAME).copy()
    s["p"] = s["p"].map(local)
    s["t"] = s["t"].astype(str).map(tmap)
    s = s.sort_values(["p", "y", "t", "o"])
    cols = {}
    for c in s.columns:
        v = s[c].to_numpy()
        cols[c] = [round(float(x), 2) for x in v] if c in FLOAT_COLS else [int(x) for x in v]
    d = db.loc[players]
    fam = d["bowling_family"].copy()
    fam_src = d["fam_src"].copy()
    if inferred_fam is not None:
        inf = inferred_fam.reindex(players).fillna("")
        use = (fam == "") & (inf != "")
        fam[use] = inf[use]
        fam_src[use] = "model"
    P = {
        "id": d["id"].tolist(), "name": d["name"].tolist(),
        "nat": d["national_team"].fillna("").tolist(), "hand": d["batting_hand"].tolist(),
        "bowl": d["bowling_class"].tolist(), "fam": fam.tolist(), "famSrc": fam_src.tolist(),
        "role": d["role"].tolist(), "dob": d["birth_date"].tolist(), "wk": d["wk"].astype(int).tolist(),
        **{k: flags[k].astype(int).tolist() for k in ("squad", "active", "retired", "pre", "overseas", "cc")},
        "last": flags["last"].astype(str).tolist(),
    }
    if ctx["captains"] is not None and flags["capt"].sum() > 0:
        P["capt"] = flags["capt"].astype(int).tolist()
        P["vc"] = flags["vc"].astype(int).tolist()
    has_squads = bool(flags["squad"].sum())
    from .model.values import FULL_MEMBERS
    full = [int(t in FULL_MEMBERS) if scope in INTL_SCOPES else 1 for t in teams]
    doc = {**meta, "teams": teams, "teamsFull": full, "players": P, "seasons": cols,
           "availability": {"squads": has_squads, "leadership": "capt" in P}}
    size = dump(doc, out / "scopes" / f"{scope}.json")
    return {"players": len(players), "rows": len(s), "bytes": size, "squads": has_squads,
            "_flags": flags}


def build_site_data(warehouse: str | Path, model_dir: str | Path, reference: str | Path,
                    competitions: str | Path, out: str | Path, *, profiles: bool = True, log=print) -> dict:
    wh = Warehouse(warehouse)
    model_dir, out = Path(model_dir), Path(out)
    ctx = build_player_db(warehouse, reference, competitions)
    summary = json.loads((model_dir / "values_summary.json").read_text(encoding="utf-8"))
    inferred = None
    inf_path = model_dir / "bowler_family.parquet"
    if inf_path.exists():
        f = pd.read_parquet(inf_path)
        inferred = f.set_index("player")["family"]
    scopes, flags_by_scope, metas = [], {}, {}
    for f in sorted((model_dir / "seasons").glob("*.parquet")):
        scope = f.stem
        if scope not in INTL_SCOPES and scope not in ctx["leagues"]:
            continue
        seasons = pd.read_parquet(f)
        meta = scope_meta(scope, wh, ctx["leagues"], summary["groups"])
        info = export_scope(scope, seasons, ctx, meta, out, inferred)
        flags_by_scope[scope] = info.pop("_flags")
        metas[scope] = meta
        scopes.append({k: meta[k] for k in ("key", "label", "tier", "gender", "format", "family", "years", "matches")}
                      | {k: meta.get(k) for k in ("short", "featured", "host")} | info)
        log(f"exported {scope}: {info}")
    manifest = json.loads((Path(warehouse) / "manifest.json").read_text(encoding="utf-8"))
    meta = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataEnd": str(wh.matches["end_date"].max()),
        "source": {"name": "Cricsheet", "url": "https://cricsheet.org/downloads/all_json.zip",
                   "sha256": manifest["source"]["sha256"], "matches": manifest["matches"],
                   "builtAt": manifest["built_at"]},
        "scopes": scopes,
        "model": {"groups": {k: {kk: vv for kk, vv in v.items() if kk != "bowling_unit_effect"}
                             for k, v in summary["groups"].items()},
                  "testWicketValue": summary["test_wicket_value"]},
    }
    if profiles:
        meta["profiles"] = build_profiles(ctx, model_dir, out, metas, flags_by_scope, summary, inferred, log=log)
    dump(meta, out / "meta.json")
    dump(summary["run_expectancy"], out / "model" / "run_expectancy.json")
    return meta


def _career(cj: str) -> dict:
    try:
        return json.loads(cj) if cj else {}
    except ValueError:
        return {}


def build_profiles(ctx: dict, model_dir: Path, out: Path, metas: dict, flags_by_scope: dict,
                   summary: dict, inferred: pd.Series | None, *, log=print) -> dict:
    """Write site/data/players/<id>.json and players/index.json."""
    from .model.archetypes import CLASS_LABELS
    from .model.profiles import PROFILE_MIN_BALLS, bowler_maps, load_scope, scope_profiles, season_trend
    db = ctx["db"]
    keepers = pd.read_parquet(model_dir / "keepers.parquet")
    group, fam, hand = bowler_maps(db, inferred)
    names = db["name"]
    blocks: dict[int, dict[str, str]] = {}
    active: dict[int, list[str]] = {}
    for scope, meta in metas.items():
        family = meta["family"]
        g = summary["groups"].get(meta["fitGroup"], {})
        sigma2 = g.get("sigma2", 6.0)
        d = load_scope(model_dir / "values", scope, keepers, group, fam, hand)
        prof = scope_profiles(d, family, sigma2, meta["lambda"]["bat"], meta["lambda"]["bowl"], names, hand,
                              fam, PROFILE_MIN_BALLS[family])
        del d
        seasons = pd.read_parquet(model_dir / "seasons" / f"{scope}.parquet")
        trend = season_trend(seasons, meta["lambda"]["bat"], meta["lambda"]["bowl"])
        flags = flags_by_scope[scope]
        # Percentiles of profile value among qualified players in this scope.
        bat_vals = pd.Series({p: b["batting"]["value"] for p, b in prof.items() if "batting" in b}, dtype=float)
        bowl_vals = pd.Series({p: b["bowling"]["value"] for p, b in prof.items() if "bowling" in b}, dtype=float)
        bat_pct, bowl_pct = bat_vals.rank(pct=True), bowl_vals.rank(pct=True)
        for p, b in prof.items():
            f = flags.loc[p] if p in flags.index else None
            block = {"label": meta["label"], "tier": meta["tier"], "format": meta["format"], "family": family,
                     "status": {k: int(f[k]) for k in ("squad", "active", "retired")} if f is not None else {},
                     "captained": int(f["capt"]) if f is not None else 0,
                     "lastPlayed": str(f["last"]) if f is not None else "",
                     "batPct": round(float(bat_pct.get(p)), 3) if p in bat_pct.index else None,
                     "bowlPct": round(float(bowl_pct.get(p)), 3) if p in bowl_pct.index else None,
                     "seasons": trend.get(p, []), **b}
            if f is not None and int(f["active"]):
                active.setdefault(p, []).append(scope)
            blocks.setdefault(p, {})[scope] = json.dumps(block, ensure_ascii=False, separators=(",", ":"),
                                                         default=_clean)
        log(f"profiles {scope}: {len(prof)} players")
    caps = ctx["captains"]
    squads = ctx["squads"]
    index = []
    pdir = out / "players"
    pdir.mkdir(parents=True, exist_ok=True)
    total = 0
    for p, by_scope in blocks.items():
        r = db.loc[p]
        cid = r["id"]
        header = {
            "id": cid, "name": r["name"], "fullName": r["full_name"], "dob": r["birth_date"],
            "nat": r["national_team"] if isinstance(r["national_team"], str) else "",
            "country": r["country"], "hand": r["batting_hand"],
            "bowl": {"class": r["bowling_class"], "label": CLASS_LABELS.get(r["bowling_class"], ""),
                     "family": r["bowling_family"] or (inferred.get(p, "") if inferred is not None else ""),
                     "source": "wikipedia" if r["bowling_family"] else ("model" if inferred is not None and inferred.get(p, "") else "")},
            "role": r["role"], "wiki": r["wikipedia_title"], "career": _career(r["career_json"]),
            "retired": {k: r[f"retired_{k}"] == "1" for k in ("test", "odi", "t20i", "international")},
            "captaincy": caps[caps["cricsheet_id"] == cid].drop(columns=["cricsheet_id"]).to_dict("records")
            if caps is not None else [],
            "squads": squads[squads["cricsheet_id"] == cid][["level", "team", "competition", "forms", "contracted",
                                                             "captain_formats", "vice_captain_formats",
                                                             "role_group", "page_timestamp"]].to_dict("records")
            if squads is not None else [],
        }
        text = (json.dumps(header, ensure_ascii=False, separators=(",", ":"), default=_clean)[:-1]
                + ',"scopes":{' + ",".join(f'"{k}":{v}' for k, v in by_scope.items()) + "}}")
        (pdir / f"{cid}.json").write_text(text, encoding="utf-8")
        total += len(text)
        index.append({"id": cid, "n": r["name"], "f": r["full_name"], "c": header["nat"] or r["country"],
                      "r": r["role"], "b": r["bowling_class"] or header["bowl"]["family"],
                      "s": list(by_scope), "a": active.get(p, [])})
    dump(index, pdir / "index.json")
    return {"players": len(index), "bytes": total}
