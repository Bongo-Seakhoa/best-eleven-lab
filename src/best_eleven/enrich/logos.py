"""Team flags and franchise logos for display, with their sources.

National sides use their country's flag from Wikidata (P41, Commons files,
mostly public domain); a few cricket sides play under their own flag and are
overridden. Franchises use the logo in their Wikipedia infobox, which is
usually a non-free file: the site shows it small, next to the team name, for
identification, and lists every file with its licence on the credits page.

Output: site/assets/img/teams/<slug>.png and site/assets/img/teams/index.json
({team: {slug, kind, file, page, licence, source}}).
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import requests

from .wiki import USER_AGENT, Wiki, infobox

# Cricket sides whose identity is not their country's state flag.
FLAG_OVERRIDES = {
    "West Indies": "File:WestIndiesCricketFlagPre1999.svg",
    "England": "File:Flag of England.svg",
    "Ireland": "File:Cricket Ireland flag.svg",
    "Scotland": "File:Flag of Scotland.svg",
    "Wales": "File:Flag of Wales.svg",
}
COUNTRY_TITLES = {
    "United States of America": "United States", "Ivory Coast": "Ivory Coast", "Czech Republic": "Czech Republic",
    "Hong Kong": "Hong Kong", "Papua New Guinea": "Papua New Guinea", "Saint Helena": "Saint Helena",
    "Isle of Man": "Isle of Man", "Jersey": "Jersey", "Guernsey": "Guernsey", "Cayman Islands": "Cayman Islands",
    "Swaziland": "Eswatini", "Eswatini": "Eswatini", "Turks and Caicos Islands": "Turks and Caicos Islands",
    "UAE": "United Arab Emirates", "ICC World XI": None, "World XI": None, "Asia XI": None, "Africa XI": None,
}
THUMB = 96


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def flag_file(wiki: Wiki, team: str) -> str | None:
    if team in FLAG_OVERRIDES:
        return FLAG_OVERRIDES[team]
    title = COUNTRY_TITLES.get(team, team)
    if title is None:
        return None
    d = wiki.api(action="query", titles=title, prop="pageprops", ppprop="wikibase_item", redirects="1")
    pages = d.get("query", {}).get("pages", [])
    qid = pages[0].get("pageprops", {}).get("wikibase_item") if pages else None
    if not qid:
        return None
    e = wiki._get("https://www.wikidata.org/w/api.php", {"action": "wbgetentities", "ids": qid, "props": "claims",
                                                          "format": "json"})
    claims = e.get("entities", {}).get(qid, {}).get("claims", {}).get("P41", [])
    preferred = [c for c in claims if c.get("rank") == "preferred"] or [c for c in claims if c.get("rank") == "normal"]
    for c in preferred:
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, str):
            return f"File:{v}"
    return None


def logo_file(wiki: Wiki, team: str, competition: str) -> tuple[str | None, str | None]:
    """The logo named in the team's infobox. Page images cannot be used here:
    the API leaves out non-free files, and club logos are almost always non-free."""
    for title in (team, f"{team} (cricket)", f"{team} (cricket team)", f"{team} cricket team"):
        page = wiki.wikitext([title]).get(title) or {}
        text = page.get("text")
        if not text or re.search(r"\{\{\s*(disambiguation|dab|hndis)", text, re.I):
            continue
        if not re.search(r"cricket|twenty20|t20|league|premier|bash|sa20|hundred", text[:4000], re.I):
            continue
        m = re.search(r"\{\{\s*Infobox[^|}]*", text, re.I)
        if not m:
            continue
        box = infobox(text, m.group(0)[2:].strip())
        for key in ("logo", "team_logo", "logo_image", "image", "crest"):
            v = box.get(key, "")
            f = re.search(r"([^\[\]|=:]+\.(?:svg|png|jpe?g|gif|webp))", v, re.I)
            # infoboxes sometimes still name a deleted file; take the first that exists
            if f and image_info(wiki, f"File:{f.group(1).strip()}"):
                return f"File:{f.group(1).strip()}", page.get("title")
    return None, None


def image_info(wiki: Wiki, file: str) -> dict | None:
    d = wiki.api(action="query", titles=file, prop="imageinfo", iiprop="url|extmetadata",
                 iiurlwidth=str(THUMB), redirects="1")
    pages = d.get("query", {}).get("pages", [])
    if not pages or "imageinfo" not in pages[0]:
        return None
    ii = pages[0]["imageinfo"][0]
    meta = ii.get("extmetadata", {})
    return {"thumb": ii.get("thumburl") or ii.get("url"), "page": ii.get("descriptionurl"),
            "licence": (meta.get("LicenseShortName") or {}).get("value", ""),
            "nonfree": (meta.get("NonFree") or {}).get("value", "") == "true"}


def run(wiki: Wiki, warehouse: str | Path, competitions: str | Path, out_dir: str | Path) -> dict:
    """Fetch an image for every team in the national scopes and mapped leagues."""
    import pandas as pd
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    leagues = {lg["key"]: lg for lg in json.loads(Path(competitions).read_text(encoding="utf-8"))["leagues"]}
    m = pd.read_parquet(Path(warehouse) / "matches.parquet", columns=["scope", "team_type", "team1", "team2"])
    m = m[(m["scope"] != "other")]
    wanted: dict[str, tuple[str, str]] = {}
    for scope, team_type, t1, t2 in m.itertuples(index=False):
        kind = "flag" if team_type == "international" else "logo"
        comp = leagues.get(scope, {}).get("label", "")
        for t in (t1, t2):
            wanted.setdefault(t, (kind, comp))
    index_path = out / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    done = missing = 0
    for team, (kind, comp) in sorted(wanted.items()):
        if team in index and (out / f"{index[team]['slug']}.png").exists():
            continue
        if kind == "flag":
            file, article = flag_file(wiki, team), None
        else:
            file, article = logo_file(wiki, team, comp)
        info = image_info(wiki, file) if file else None
        if not info or not info["thumb"]:
            missing += 1
            continue
        r = session.get(info["thumb"], timeout=60)
        if r.status_code != 200 or not r.headers.get("Content-Type", "").startswith("image/"):
            missing += 1
            continue
        sl = slug(team)
        (out / f"{sl}.png").write_bytes(r.content)
        index[team] = {"slug": sl, "kind": kind, "file": file.replace("File:", ""), "page": info["page"],
                       "licence": info["licence"] or ("Non-free logo" if info["nonfree"] else ""),
                       "nonfree": info["nonfree"], "article": article or ""}
        done += 1
    index_path.write_text(json.dumps(dict(sorted(index.items())), indent=1, ensure_ascii=False), encoding="utf-8")
    return {"teams": len(wanted), "with_image": len(index), "fetched_now": done, "missing": missing}
