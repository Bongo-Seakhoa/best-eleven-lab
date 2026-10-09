"""End-to-end pipeline: fetch -> ingest -> enrich -> model -> validate -> export."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import sources

ROOT = Path.cwd()


class Paths:
    def __init__(self, root: str | Path = "."):
        r = Path(root)
        self.raw = r / "data" / "raw"
        self.warehouse = r / "data" / "warehouse"
        self.model = r / "data" / "model"
        self.reference = r / "data" / "reference"
        self.cache = r / "data" / "cache" / "wiki"
        self.competitions = r / "config" / "competitions.json"
        self.site = r / "site"
        self.site_data = r / "site" / "data"


def _timed(label: str, log):
    class T:
        def __enter__(self):
            self.t = time.time(); log(f"> {label}"); return self

        def __exit__(self, *exc):
            if exc[0] is None:
                log(f"  {label} done in {time.time() - self.t:.0f}s")
    return T()


def fetch(p: Paths, *, force: bool = False, log=print) -> dict:
    with _timed("fetch", log):
        return {k: sources.fetch(k, p.raw, force=force, log=log) for k in sources.SOURCES}


def ingest(p: Paths, *, log=print) -> dict:
    from .ingest import build_warehouse
    with _timed("ingest", log):
        m = build_warehouse(p.raw / "all_json.zip", p.warehouse, p.competitions,
                            progress=lambda i, n: log(f"  {i:,}/{n:,} matches") if i % 6000 == 0 else None)
        log(f"  {m['matches']:,} matches, {m['players']:,} players, {m['quarantined']} quarantined")
        return m


def enrich(p: Paths, *, refresh: bool = False, log=print) -> dict:
    """Refresh the Wikipedia/Wikidata reference snapshots (network)."""
    from .enrich import captains, careers, players, squads
    from .enrich.wiki import Resolver, Wiki
    wiki = Wiki(p.cache, min_interval=0.5, refresh=refresh)
    resolver = Resolver(p.raw / "people.csv", wiki)
    out = {}
    for name, mod in (("careers", careers), ("captains", captains), ("squads", squads), ("players", players)):
        with _timed(f"enrich {name}", log):
            stats = mod.run(wiki, resolver, p.reference, warehouse=p.warehouse)
            out[name] = {k: v for k, v in stats.items() if not isinstance(v, (list, dict)) or len(str(v)) < 400}
    from .enrich import logos
    with _timed("enrich team images", log):
        out["team_images"] = logos.run(wiki, p.warehouse, p.competitions, p.site / "assets" / "img" / "teams")
    manifest = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "English Wikipedia and Wikidata (CC BY-SA 4.0 / CC0)", "modules": out}
    (p.reference / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    return manifest


def wiki_keepers(p: Paths) -> set[int]:
    path = p.reference / "players_wiki.csv"
    if not path.exists():
        return set()
    w = pd.read_csv(path, dtype=str, keep_default_na=False)
    ids = set(w.loc[w["role"].str.contains("wicket-keeper", na=False) & (w["cricsheet_id"] != ""), "cricsheet_id"])
    players = pd.read_parquet(p.warehouse / "players.parquet")
    return set(players.loc[players["id"].isin(ids), "player"].astype(int))


def model(p: Paths, *, log=print) -> dict:
    from .model.aggregate import build_aggregates
    from .model.archetypes import build_bowler_families
    from .model.values import build_values
    p.model.mkdir(parents=True, exist_ok=True)
    with _timed("value deliveries", log):
        build_values(p.warehouse, p.competitions, p.model, log=lambda m: log("  " + m[:140]))
    with _timed("season aggregates", log):
        build_aggregates(p.warehouse, p.model, wiki_keepers=wiki_keepers(p), log=lambda m: None)
    with _timed("bowling-type classifier", log):
        metrics = build_bowler_families(p.warehouse, p.model, p.reference)
        log(f"  cv accuracy {metrics['cv_accuracy']}, confident accuracy {metrics['cv_confident_accuracy']}")
    return metrics


def validate(p: Paths, *, log=print) -> dict:
    from .validate import run_checks
    with _timed("validate", log):
        report = run_checks(p.warehouse, p.model, p.reference)
        for c in report["checks"]:
            log(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['name']}: {c['summary']}")
        return report


def export(p: Paths, *, profiles: bool = True, log=print) -> dict:
    from .export import build_site_data, dump
    with _timed("export site data", log):
        meta = build_site_data(p.warehouse, p.model, p.reference, p.competitions, p.site_data,
                               profiles=profiles, log=lambda m: None)
        val = p.model / "validation.json"
        if val.exists():
            dump(json.loads(val.read_text(encoding="utf-8")), p.site_data / "validation.json")
        dump(reference_summary(p), p.site_data / "reference.json")
        fam = p.model / "bowler_family_metrics.json"
        if fam.exists():
            dump(json.loads(fam.read_text(encoding="utf-8")), p.site_data / "model" / "bowler_family.json")
        log(f"  {len(meta['scopes'])} scopes, {meta.get('profiles', {}).get('players', 0):,} profiles")
        return meta


def reference_summary(p: Paths) -> dict:
    """Counts straight from the committed snapshots, so the site always describes
    exactly the reference data it was built with."""
    def csv(name):
        path = p.reference / name
        return pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else None
    manifest = p.reference / "manifest.json"
    fetched = json.loads(manifest.read_text(encoding="utf-8")).get("fetched_at", "") if manifest.exists() else ""
    mods = {}
    w = csv("players_wiki.csv")
    if w is not None:
        mods["player_attributes"] = {"articles": len(w), "linked_to_cricsheet": int((w["cricsheet_id"] != "").sum()),
                                     "batting_hand": int((w["batting_hand"] != "").sum()),
                                     "bowling_style": int((w["bowling_class"] != "").sum()),
                                     "retirements_recorded": int((w["retired_international"] == "1").sum())}
    c = csv("careers_lists.csv")
    if c is not None:
        mods["historic_careers"] = {"careers": len(c), "lists": int(c["source_page"].nunique()),
                                    "linked_to_cricsheet": int((c["cricsheet_id"] != "").sum())}
    t = csv("captain_totals.csv")
    if t is not None:
        mods["captaincy"] = {"captaincy_records": len(t), "captains": int(t["wikipedia_title"].replace("", None).nunique()),
                             "linked_to_cricsheet": int((t["cricsheet_id"] != "").sum())}
    q = csv("squads.csv")
    if q is not None:
        mods["current_squads"] = {"squad_places": len(q), "teams": int(q[["team", "competition"]].drop_duplicates().shape[0]),
                                  "linked_to_cricsheet": int((q["cricsheet_id"] != "").sum())}
    imgs = p.site / "assets" / "img" / "teams" / "index.json"
    if imgs.exists():
        idx = json.loads(imgs.read_text(encoding="utf-8"))
        mods["team_images"] = {"flags": sum(1 for v in idx.values() if v["kind"] == "flag"),
                               "logos": sum(1 for v in idx.values() if v["kind"] == "logo")}
    return {"source": "English Wikipedia and Wikidata (CC BY-SA 4.0 / CC0)", "fetched_at": fetched, "modules": mods}
