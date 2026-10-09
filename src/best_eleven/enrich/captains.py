"""Formal captaincy records from Wikipedia captaincy list pages.

International pages ("List of South Africa national cricket captains", "List of
England cricket captains", ...) carry one wikitable per gender and format.
Test tables are usually one row per series with a "Total" row per captain;
ODI/T20I tables are usually one row per captain. Franchise pages ("List of
Indian Premier League captains", ...) carry one row per captain across all the
teams he led in that competition.

Outputs (data/reference/):
  captains.csv        one row per source row that is not a total row.
  captain_totals.csv  aggregated per (level, country_or_team, competition,
                      gender, format, wikipedia_title or name).

Conventions beyond the shared vocabularies:
  * Youth, vice-captain, ICC-tournament, rebel, World Series and Rest of the
    World tables are skipped, as are tables whose format cannot be inferred.
  * Franchise rows use format 'T20' (the warehouse's franchise format code);
    country_or_team is the team or teams in the row's "Team(s)" cell, joined
    with '; ' because the source does not split a captain's record by team.
  * Counts the source leaves blank, as a dash, or as anything but a whole
    number (e.g. a win percentage in a count column) stay blank. An aggregate
    count is blank when any of its source rows lacks that count.
  * Tables with captain and played columns that are skipped only because no
    format can be inferred are listed in the run report's page_problems.
  * wikipedia_title is left blank when the name links nowhere, to a list page,
    or to an article that is not about a cricketer (no cricinfo id, no
    cricketer infobox or category).
  * cricsheet_id comes from Resolver.resolve_titles. When the article has no
    cricinfo id there, an ESPNcricinfo profile URL in the article is used if it
    is unambiguous, its Cricsheet surname matches, and (for international rows)
    the warehouse does not show that id playing only for other teams.

Extra columns:
  captains.csv:       source_table (caption or heading the row came from),
                      notes ('deputised' for rows marked with a dagger,
                      'drawn includes tied' / 'tied includes no result' where
                      the source merges those columns, 'results exceed played'
                      or 'results short of played' when the row's own counts
                      (all present) do not add up, 'tied exceeds
                      lost' when a limited-overs row looks like the page swapped
                      its Lost and Tied values). Flags never change the counts.
  captain_totals.csv: revid, rows (source rows aggregated), ongoing (1 when a
                      period reads "present"; last_year is then blank),
                      page_total ('match' /
                      'mismatch' against the page's own Total rows, '' when
                      the page has none), page_total_detail (which counts
                      disagree, page value vs summed rows), notes (row flags
                      other than 'deputised').
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .wiki import Resolver, Wiki, infobox, title_from_url

COUNTRIES = ["Australia", "England", "South Africa", "India", "New Zealand", "Pakistan",
             "Sri Lanka", "West Indies", "Bangladesh", "Zimbabwe", "Afghanistan", "Ireland",
             "Scotland", "Netherlands", "United Arab Emirates", "Nepal", "Oman", "Namibia",
             "United States of America", "Canada", "Kenya", "Hong Kong", "Papua New Guinea",
             "Bermuda", "East Africa"]
WIKI_COUNTRY = {"United States of America": "United States"}
FRANCHISE = [("Indian Premier League", "male"), ("Big Bash League", "male"),
             ("Pakistan Super League", "male"), ("Caribbean Premier League", "male"),
             ("SA20", "male"), ("Bangladesh Premier League", "male"),
             ("Lanka Premier League", "male"), ("International League T20", "male"),
             ("Major League Cricket", "male"), ("Champions League Twenty20", "male"),
             ("Women's Premier League", "female"), ("Women's Big Bash League", "female"),
             ("Women's Caribbean Premier League", "female")]

CAPTAIN_COLS = ["level", "country_or_team", "competition", "gender", "format", "name",
                "wikipedia_title", "cricsheet_id", "number", "season_or_period", "opposition",
                "location", "played", "won", "lost", "drawn", "tied", "no_result",
                "source_page", "revid", "source_table", "notes"]
TOTAL_COLS = ["level", "country_or_team", "competition", "gender", "format", "name",
              "wikipedia_title", "cricsheet_id", "first_year", "last_year", "played", "won",
              "lost", "drawn", "tied", "no_result", "win_pct", "source_page", "revid", "rows",
              "ongoing", "page_total", "page_total_detail", "notes"]
STATS = ["played", "won", "lost", "drawn", "tied", "no_result"]

SKIP_RE = re.compile(r"youth|under[- ]?19|\bu-?19|vice|\bicc\b|trophy|tournament|world cup|"
                     r"qualifier|champions trophy|rebel|world series|supertest|\bwsc\b|"
                     r"rest of the world|6 nations|overall|most successful|\bother\b|\bkey\b",
                     re.I)
FORMAT_RES = [("Test", re.compile(r"\bw?tests?\b", re.I)),
              ("ODI", re.compile(r"\bw?odis?\b|one[- ]day", re.I)),
              ("T20I", re.compile(r"\bw?t20is?\b|twenty ?20|\bt20\b", re.I))]

# header text -> (field, note when the source merges two outcomes)
HEADER = {
    "number": "number", "no": "number", "no.": "number", "s.no.": "number", "sl. no.": "number",
    "#": "number",
    "name": "name", "player": "name", "captain": "name",
    "season": "period", "year": "period", "year(s)": "period", "years": "period",
    "period": "period", "period of captaincy": "period", "span": "period",
    "first": "first", "last": "last",
    "opposition": "opposition", "opponent": "opposition", "opponents": "opposition",
    "location": "location", "venue": "location",
    "played": "played", "matches": "played", "mat": "played", "match(es)": "played",
    "won": "won", "w": "won", "lost": "lost", "l": "lost",
    "drawn": "drawn", "d": "drawn", "draw": "drawn",
    "d/t": ("drawn", "drawn includes tied"), "drawn/tied": ("drawn", "drawn includes tied"),
    "tied": "tied", "tie": "tied", "t": "tied",
    "t/nr": ("tied", "tied includes no result"), "tied/nr": ("tied", "tied includes no result"),
    "tie/nr": ("tied", "tied includes no result"),
    "no result": "no_result", "nr": "no_result", "n/r": "no_result", "noresult": "no_result",
    "nor": "no_result",
    "team(s)": "teams", "team": "teams", "teams": "teams",
}
TOTAL_RE = re.compile(r"^((grand )?totals?|overall):?$", re.I)
MARKS = "†‡*§#^"  # dagger, double dagger and other footnote marks


# ------------------------------------------------------------------ discovery
def _existing(wiki: Wiki, titles: list[str]) -> dict[str, str]:
    """Requested title -> resolved title, for titles that exist."""
    out = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        q = wiki.api(action="query", titles="|".join(batch), redirects="1").get("query", {})
        alias = {m["from"]: m["to"] for k in ("normalized", "redirects") for m in q.get(k, [])}
        pages = {p["title"]: p for p in q.get("pages", [])}
        for t in batch:
            final = t
            for _ in range(4):
                final = alias.get(final, final)
            p = pages.get(final)
            if p and not p.get("missing") and not p.get("invalid"):
                out[t] = final
    return out


def _is_list_page(title: str, subject: str) -> bool:
    t = title.lower()
    return (t.startswith("list of ") and t.endswith(" captains") and subject.lower() in t
            and "women" not in t.replace(subject.lower(), "")
            and not re.search(r"under|youth|county|premiership|football", t))


def _search(wiki: Wiki, subject: str) -> str | None:
    d = wiki.api(action="query", list="search", srsearch=f'intitle:captains "{subject}" cricket',
                 srlimit="20", srnamespace="0")
    for r in d.get("query", {}).get("search", []):
        if _is_list_page(r["title"], subject):
            return r["title"]
    return None


def discover(wiki: Wiki) -> tuple[list[dict], list[str]]:
    """Captaincy list pages to parse, plus a note for every subject without one."""
    wanted = []
    for c in COUNTRIES:
        w = WIKI_COUNTRY.get(c, c)
        wanted.append(("international", c, "", "", [f"List of {w} national cricket captains",
                                                      f"List of {w} cricket captains",
                                                      f"List of {w} national cricket team captains"], w))
    for comp, gender in FRANCHISE:
        wanted.append(("franchise", "", comp, gender, [f"List of {comp} captains",
                                                        f"List of {comp} cricket captains"], comp))
    found = _existing(wiki, [t for *_, cands, _ in wanted for t in cands])
    pages, missing = [], []
    for level, country, comp, gender, cands, subject in wanted:
        title = next((found[t] for t in cands if t in found and _is_list_page(found[t], subject)), None)
        title = title or _search(wiki, subject)
        if title:
            pages.append({"level": level, "country": country, "competition": comp,
                          "gender": gender, "title": title})
        else:
            missing.append(f"{level}: {country or comp} (tried {cands[0]!r} and search)")
    return pages, missing


# -------------------------------------------------------------------- tables
def _clean(s: str) -> str:
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = s.replace("–", "-").replace("—", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _cell(el) -> dict:
    for x in el.xpath(".//sup[contains(@class,'reference')]|.//style|.//*[contains(@style,'display:none')]"
                      "|.//*[contains(@class,'sortkey')]"):
        x.drop_tree()
    for br in el.xpath(".//br"):
        br.tail = " " + (br.tail or "")
    raw = el.text_content()  # keeps dagger marks that sit in <sup>
    for x in el.xpath(".//sup"):  # remaining sups are footnote numbers, e.g. "3<sup>5,7</sup>"
        x.drop_tree()
    links = []
    for a in el.xpath(".//a[starts-with(@href,'/wiki/')]"):
        t = title_from_url(a.get("href").split("#")[0])
        if t and ":" not in t and a.text_content().strip():
            links.append(t)
    text = _clean(el.text_content())
    return {"text": text.strip(MARKS + " ").strip(), "raw": _clean(raw), "links": links,
            "th": el.tag == "th"}


def grid(table) -> list[list[dict]]:
    """Rows of cells with rowspan/colspan expanded (spanned cells repeat)."""
    rows, pending = [], {}
    for tr in table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr"):
        row, col = [], 0
        cells = [(_cell(c), int(re.sub(r"\D", "", c.get("rowspan") or "1") or 1),
                  int(re.sub(r"\D", "", c.get("colspan") or "1") or 1))
                 for c in tr.xpath("./td|./th")]
        for cell, rs, cs in cells:
            while col in pending:
                row.append(pending[col][1])
                pending[col][0] -= 1
                if not pending[col][0]:
                    del pending[col]
                col += 1
            for _ in range(cs):
                row.append(cell)
                if rs > 1:
                    pending[col] = [rs - 1, cell]
                col += 1
        while col in pending:
            row.append(pending[col][1])
            pending[col][0] -= 1
            if not pending[col][0]:
                del pending[col]
            col += 1
        rows.append(row)
    return rows


def page_tables(html: str) -> list[dict]:
    """Every wikitable with its heading context, caption and expanded grid."""
    from lxml import html as lh
    tree = lh.fromstring(html)
    heads: dict[str, str] = {}
    out = []
    levels = ("h2", "h3", "h4")
    for el in tree.iter(*levels, "table"):
        if el.tag != "table":
            heads[el.tag] = _clean(el.text_content())
            for lower in levels[levels.index(el.tag) + 1:]:
                heads.pop(lower, None)
            continue
        if "wikitable" not in (el.get("class") or "") or el.xpath("ancestor::table"):
            continue
        cap = el.xpath("./caption")
        caption = _clean(cap[0].text_content()) if cap else ""
        rows = grid(el)
        header, body = None, []
        for r in rows:
            if not r:
                continue
            if all(c["th"] for c in r) and not any(TOTAL_RE.match(c["text"]) for c in r):
                if len({id(c) for c in r}) == 1:
                    caption = caption or r[0]["text"]
                elif header is None or not body:
                    header = [c["text"] for c in r]
                continue
            body.append(r)
        out.append({"headings": [heads.get(h, "") for h in levels],
                    "caption": caption, "header": header or [], "rows": body})
    return out


def classify(t: dict, level: str, page_gender: str = "") -> tuple[str, str] | None:
    """(gender, format) of a table, or None to skip it."""
    ctx = " ".join([*t["headings"], t["caption"]])
    if SKIP_RE.search(ctx):
        return None
    if level == "franchise":
        return page_gender or "male", "T20"
    gender = "female" if re.search(r"\bwomen", ctx, re.I) else "male"
    for part in [t["caption"], *reversed(t["headings"])]:
        for fmt, rx in FORMAT_RES:
            if part and rx.search(part):
                return gender, fmt
    return None


def _columns(header: list[str]) -> tuple[dict[str, int], list[str]]:
    cols, notes = {}, []
    for i, h in enumerate(header):
        key = HEADER.get(_clean(h).lower().strip(MARKS + " "))
        if isinstance(key, tuple):
            key, note = key
            notes.append(note)
        if key and key not in cols:
            cols[key] = i
    return cols, notes


def _int(s: str) -> int | None:
    s = (s or "").strip()
    return int(s) if re.fullmatch(r"\d+", s) else None


def _tail_counts(r: list[dict]) -> int:
    """Number of whole-number cells at the end of a row."""
    n = 0
    for c in reversed(r):
        if not re.fullmatch(r"\d+", c["text"]):
            break
        n += 1
    return n


def parse_table(t: dict) -> tuple[list[dict], list[dict]]:
    """Source rows and explicit Total rows of one captains table (unresolved).

    Each captain Total row is checked against the rows of that captain since the
    previous Total row (its "block"); a team Total row against the whole table."""
    cols, notes = _columns(t["header"])
    if "name" not in cols or "played" not in cols:
        return [], []
    rows, totals, block = [], [], []
    pad = {"text": "", "raw": "", "links": [], "th": False}
    per_series = "opposition" in cols or "location" in cols
    width = len(t["header"])
    for r in t["rows"]:
        if (len(r) < width and any(TOTAL_RE.match(c["text"]) for c in r)
                and (per_series or _tail_counts(r) == width - cols["played"])):
            # short Total row (a rowspan ended, or the label spans too few
            # columns): its counts still sit at the right
            r = [pad] * (width - len(r)) + r
        get = lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else None  # noqa: E731
        name_cell = get("name")
        if name_cell is None or len({id(c) for c in r}) == 1:  # footnote rows span the table
            continue
        stats = {k: _int(get(k)["text"]) if get(k) else None for k in STATS}
        rec = {"name": name_cell["text"],
               "link": name_cell["links"][0] if name_cell["links"] else None,
               "number": get("number")["text"] if get("number") else "",
               **stats}
        rec["key"] = rec["link"] or rec["name"]
        team = bool(TOTAL_RE.match(name_cell["text"]))
        if team or any(TOTAL_RE.match(c["text"]) for c in r if c is not name_cell):
            team = team or not (name_cell["text"] or block)
            if team:
                rec.update(name="", link=None, key="")
            elif not name_cell["text"]:  # total row without the captain's name: closes the block
                rec.update(name=block[-1]["name"], link=block[-1]["link"], key=block[-1]["key"])
            src = rows if team else [b for b in block if b["key"] == rec["key"]]
            sums = {k: sum(b[k] or 0 for b in src) for k in STATS}
            rec.update(team_total=team, rows=len(src),
                       diff={k: (rec[k], sums[k]) for k in STATS
                             if rec[k] is not None and rec[k] != sums[k]})
            totals.append(rec)
            block = []
            continue
        if not rec["name"] or all(v is None for v in stats.values()):
            continue
        period = get("period")["text"] if get("period") else ""
        if not period and (get("first") or get("last")):
            a, b = (get("first") or {}).get("text", ""), (get("last") or {}).get("text", "")
            period = a if a == b or not b else f"{a}-{b}" if a else b
        row_notes = list(notes)
        marked = [c for c in (get("period"), name_cell) if c]
        if any(re.search("[†‡]", c["raw"]) for c in marked):
            row_notes.insert(0, "deputised")
        results = [stats[k] for k in STATS[1:] if k in cols]
        if stats["played"] is not None and sum(v or 0 for v in results) > stats["played"]:
            row_notes.append("results exceed played")
        elif stats["played"] is not None and results and None not in results \
                and sum(results) < stats["played"]:
            row_notes.append("results short of played")
        if not per_series and (stats["tied"] or 0) >= 3 and stats["tied"] > (stats["lost"] or 0):
            row_notes.append("tied exceeds lost")  # usually Lost/Tied values swapped on the page
        teams = get("teams")
        rec.update(season_or_period=period,
                   opposition=get("opposition")["text"] if get("opposition") else "",
                   location=get("location")["text"] if get("location") else "",
                   teams="; ".join(dict.fromkeys(teams["links"])) or teams["text"] if teams else "",
                   notes="; ".join(row_notes))
        if block and block[-1]["key"] != rec["key"]:
            block = []
        block.append(rec)
        rows.append(rec)
    return rows, totals


# --------------------------------------------------------------- aggregation
YEAR_RE = re.compile(r"(1[89]\d\d|20\d\d)(?:\s*[-/]\s*(\d{4}|\d{1,2})(?!\d))?")


def years(text: str) -> list[int]:
    """Years named in a season or period: '1888-89' -> [1888, 1889], '1934/5' ->
    [1934, 1935], '1999/00' -> [1999, 2000], '2021-present' -> [2021]."""
    out = []
    for a, b in YEAR_RE.findall(text or ""):
        a = int(a)
        out.append(a)
        if len(b) == 4:
            out.append(int(b))
        elif b:
            step = 10 ** len(b)
            end = a - a % step + int(b)
            out.append(end + step if end < a else end)
    return out


def _sum(s: pd.Series):
    v = pd.to_numeric(s, errors="coerce")
    return int(v.sum()) if len(v) and v.notna().all() else None  # partial sums are not totals


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    keys = ["level", "country_or_team", "competition", "gender", "format", "who"]
    df = df.assign(who=df["wikipedia_title"].where(df["wikipedia_title"].astype(bool), df["name"]))
    recs = []
    for k, g in df.groupby(keys, sort=False):
        ys = [y for p in g["season_or_period"] for y in years(p)]
        ongoing = bool(g["season_or_period"].str.contains("present", case=False).any())
        rec = dict(zip(keys, k))
        rec.update(name=g["name"].iloc[0], wikipedia_title=g["wikipedia_title"].iloc[0],
                   cricsheet_id=g["cricsheet_id"].iloc[0],
                   first_year=min(ys) if ys else None,
                   last_year=max(ys) if ys and not ongoing else None,
                   **{s: _sum(g[s]) for s in STATS},
                   source_page=g["source_page"].iloc[0], revid=g["revid"].iloc[0], rows=len(g),
                   ongoing=int(ongoing),
                   ckeys=set(g["key"]),
                   notes="; ".join(sorted({n for x in g["notes"] for n in x.split("; ")
                                           if n and n != "deputised"})))
        p, w = rec["played"], rec["won"]
        rec["win_pct"] = round(w / p * 100, 1) if p and w is not None else None
        recs.append(rec)
    return pd.DataFrame(recs)


# ---------------------------------------------------------------------- run
def collect(wiki: Wiki, pages: list[dict]) -> tuple[pd.DataFrame, list[dict], list[str]]:
    """Parse every page into captain rows; also return explicit Total rows."""
    rows, totals, problems = [], [], []
    for pg in pages:
        try:
            p = wiki.parse(pg["title"])
        except KeyError as e:
            problems.append(f"{pg['title']}: {e}")
            continue
        used = 0
        for t in page_tables(p["html"]):
            kind = classify(t, pg["level"], pg["gender"])
            label = " > ".join(dict.fromkeys(h for h in [*t["headings"], t["caption"]] if h))
            if not kind:
                if not SKIP_RE.search(label) and parse_table(t)[0]:
                    problems.append(f"{p['title']}: table {label!r} skipped, format not inferable")
                continue
            got, tot = parse_table(t)
            if not got:
                continue
            used += 1
            gender, fmt = kind
            base = {"level": pg["level"], "competition": pg["competition"], "gender": gender,
                    "format": fmt, "source_page": p["title"], "revid": p["revid"],
                    "source_table": label}
            for r in got:
                team = r.pop("teams") if pg["level"] == "franchise" else pg["country"]
                rows.append({**base, "country_or_team": team, **r})
            for r in tot:
                totals.append({**base, "country_or_team": pg["country"], **r})
        if not used:
            problems.append(f"{p['title']}: no captain tables recognised")
    return pd.DataFrame(rows), totals, problems


CRICKETER_RE = re.compile(r"\{\{\s*Infobox cricketer|\[\[Category:[^\]]*cricketers", re.I)
PROFILE_RE = re.compile(r"cricinfo\.com/(?:[a-z]+/)*player/(?:[a-z0-9-]*-)?(\d+)", re.I)


def fallback_cricsheet(page: dict, by_cricinfo: dict[int, str], cs_name: dict[str, str]) -> str | None:
    """Cricsheet id from ESPNcricinfo profile URLs when the article has neither a
    Wikidata cricinfo id nor a {{Cricinfo|id=}} template. Takes the infobox
    source URL, else profile URLs in the text; accepts exactly one candidate
    whose Cricsheet surname matches the article title."""
    text = page.get("text") or ""
    surname = (re.sub(r"\s*\(.*\)$", "", page.get("title") or "").split() or [""])[-1].lower()
    cands = PROFILE_RE.findall(infobox(text).get("source", "")) or PROFILE_RE.findall(text)
    hits = {by_cricinfo.get(int(c)) for c in cands} - {None}
    hits = {h for h in hits if (cs_name.get(h, "").split() or [""])[-1].lower() == surname}
    return hits.pop() if len(hits) == 1 else None


def resolve(df: pd.DataFrame, resolver: Resolver, people_csv: str | Path) -> tuple[pd.DataFrame, list[str]]:
    """Add wikipedia_title, cricsheet_id and fallback_id; also return linked
    titles rejected as not being about a cricketer."""
    links = sorted({x for x in df["link"] if isinstance(x, str)})
    res = resolver.resolve_titles(links)
    people = pd.read_csv(people_csv, dtype=str, usecols=["identifier", "name"])
    cs_name = dict(zip(people["identifier"], people["name"].fillna("")))
    for v in res.values():
        if not v.get("revid") or v["title"].startswith("List of"):  # redlink, or redirect to a list
            v.update(title="", cricsheet_id=None)
        elif not v.get("cricinfo") and not CRICKETER_RE.search(v.get("text") or ""):
            v.update(title="", cricsheet_id=None, rejected=v["title"])  # page links a namesake
        elif not v.get("cricsheet_id") and not v.get("cricinfo"):
            v["cricsheet_id"] = fallback_cricsheet(v, resolver.by_cricinfo, cs_name)
            v["fallback"] = bool(v["cricsheet_id"])
    canon = {t: v["title"] for t, v in res.items()}
    cs = {t: v.get("cricsheet_id") or "" for t, v in res.items()}
    df["wikipedia_title"] = df["link"].map(lambda x: canon.get(x, "") if isinstance(x, str) else "")
    df["cricsheet_id"] = df["link"].map(lambda x: cs.get(x, "") if isinstance(x, str) else "")
    df["fallback_id"] = df["link"].map(lambda x: bool(res.get(x, {}).get("fallback")))
    return df, sorted(v["rejected"] for v in res.values() if v.get("rejected"))


def team_appearances(warehouse: str | Path) -> tuple[set[str], set[tuple[str, str]]] | None:
    """(Cricsheet ids in the warehouse, {(id, team)} pairs with an appearance)."""
    wh = Path(warehouse)
    if not (wh / "appearances.parquet").exists():
        return None
    app = pd.read_parquet(wh / "appearances.parquet", columns=["team", "player"])
    ids = pd.read_parquet(wh / "players.parquet", columns=["player", "id"])
    code = dict(zip(ids["player"], ids["id"]))
    return set(ids["id"]), set(zip(app["player"].map(code), app["team"].astype(str)))


def check_totals(totals: list[dict], agg: pd.DataFrame) -> list[str]:
    """Flag each aggregate against the page's own Total rows; list mismatches."""
    issues, flag = [], {}
    for t in totals:
        who = t["name"] or "team total"
        if t["diff"]:
            issues.append(f"{t['source_page']} | {t['source_table']} | {who}: "
                          + ", ".join(f"{k} page {a} vs rows {b}" for k, (a, b) in t["diff"].items()))
        if t["team_total"]:
            continue
        k = (t["source_page"], t["gender"], t["format"], t["key"])
        flag.setdefault(k, []).append("; ".join(f"{s} page {a} vs rows {b}"
                                                for s, (a, b) in t["diff"].items()))
    status, detail = [], []
    for r in agg.itertuples():
        found = [d for k in r.ckeys for d in flag.get((r.source_page, r.gender, r.format, k), [])]
        status.append("" if not found else "mismatch" if any(found) else "match")
        detail.append(" | ".join(d for d in found if d))
    agg["page_total"], agg["page_total_detail"] = status, detail
    return issues


def check_appearances(caps: pd.DataFrame, seen) -> dict:
    """Share of resolved international captains present in the warehouse who
    have appearances for the team they captained."""
    if not seen:
        return {}
    known, played_for = seen
    x = caps[(caps["level"] == "international") & caps["cricsheet_id"].astype(bool)]
    x = x.drop_duplicates(["country_or_team", "cricsheet_id"])
    x = x[x["cricsheet_id"].isin(known)]
    ok = [(c, t) in played_for for c, t in zip(x["cricsheet_id"], x["country_or_team"])]
    bad = x.loc[[not o for o in ok], ["country_or_team", "name", "cricsheet_id"]]
    return {"captains_in_warehouse": len(x), "with_team_appearances": int(sum(ok)),
            "without_team_appearances": [" | ".join(r) for r in bad.astype(str).values.tolist()]}


def run(wiki: Wiki, resolver: Resolver, out_dir: str | Path = "data/reference",
        warehouse: str | Path = "data/warehouse", people_csv: str | Path = "data/raw/people.csv") -> dict:
    pages, missing = discover(wiki)
    rows, totals, problems = collect(wiki, pages)
    rows, rejected = resolve(rows, resolver, people_csv)
    seen = team_appearances(warehouse)
    dropped = []
    if seen:  # a URL-derived id must not contradict the warehouse
        known, played_for = seen
        for i in rows.index[rows["fallback_id"] & (rows["level"] == "international")]:
            cid, team = rows.at[i, "cricsheet_id"], rows.at[i, "country_or_team"]
            if cid in known and (cid, team) not in played_for:
                dropped.append(f"{rows.at[i, 'name']} ({team}): {cid}")
                rows.at[i, "cricsheet_id"] = ""
    for c in ("number", "season_or_period", "opposition", "location", "notes"):
        rows[c] = rows[c].fillna("")
    agg = aggregate(rows)
    issues = check_totals(totals, agg)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    caps = rows[CAPTAIN_COLS].copy()
    for s in STATS:
        caps[s] = caps[s].astype("Int64")
    caps.to_csv(out / "captains.csv", index=False, encoding="utf-8")
    tot = agg[TOTAL_COLS].copy()
    for s in STATS + ["first_year", "last_year"]:
        tot[s] = tot[s].astype("Int64")
    tot.to_csv(out / "captain_totals.csv", index=False, encoding="utf-8")

    linked = caps["wikipedia_title"].astype(bool)
    return {"pages": [p["title"] for p in pages], "pages_missing": missing,
            "page_problems": problems, "rows": len(caps), "totals": len(tot),
            "rows_linked": int(linked.sum()),
            "rows_cricsheet": int(caps["cricsheet_id"].astype(bool).sum()),
            "totals_cricsheet": int(tot["cricsheet_id"].astype(bool).sum()),
            "total_row_mismatches": issues,
            "appearance_check": check_appearances(caps, seen),
            "fallback_ids": int(rows.loc[rows["cricsheet_id"].astype(bool), "fallback_id"].sum()),
            "fallback_ids_rejected": sorted(set(dropped)),
            "links_not_cricketers": rejected,
            "counts": caps.assign(subject=caps["country_or_team"].where(
                caps["level"] == "international", caps["competition"]))
                .groupby(["subject", "gender", "format"]).size().to_dict()}
