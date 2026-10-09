"""Complete international career records from Wikipedia "List of ... cricketers" pages.

Cricsheet ball-by-ball coverage starts around 2002, so these lists are the only
whole-career view of earlier players. One output row per (list, player): the
player's cap number, first/last year and the batting, bowling and fielding
totals exactly as the page shows them. Totals are for that team only: a player
who also played for another side (e.g. the ICC World XI, so Kallis shows 13,206
Test runs, not 13,289) has that record on the other side's list.

Pages are discovered per (country, gender, format) from the usual title patterns
("List of South Africa ODI cricketers", "List of Australia women Twenty20
International cricketers", ...), following redirects; anything not found that
way falls back to the MediaWiki search API and the "Lists of <country>
cricketers" navigation page. Sub-pages linked from a list page ("... (1877-1914)")
are read as part of the same list. Associate Test lists are tried by title
pattern only (e.g. the one-off Netherlands women Test).

Every wikitable with a name and a matches column is read. Header layouts differ
(multi-level, inverted Batting/Bowling group rows, Career spans instead of
First/Last, combined 100/50 cells), so columns are mapped by label plus the
batting/bowling section they sit in. Header-repeat, total and footnote rows
are dropped. Name-cell markers are stripped and recorded according to the
page's own legend; when a page has no legend for a marker the convention used
by every list page checked (double dagger = captain, dagger = wicket-keeper) is
assumed and the page is listed under ``legend_assumed`` in the run summary.

Conventions:
  * Values the page leaves blank or as a dash stay blank; nothing is derived.
    Unreadable cells (typos, leftover markup, lower bounds such as "5098+")
    are left blank and named in parse_note.
  * A body row with fewer cells than the header (a broken source row) keeps
    its values up to the first unreadable cell; later values are blanked
    because they have shifted into the wrong columns.
  * Values that cannot all be true together are blanked together and the
    page's values named in parse_note: not-outs above innings, innings above
    the matches allow, highest score above runs, runs above innings x highest
    score, hundreds/fifties impossible with the highest score or runs, wickets
    above balls, a best analysis beyond the career wickets or runs conceded.
    Matches are never blanked. An average that cannot be true (0 with runs,
    above total runs, positive with no runs, more dismissals than innings, a
    bowling average with no wickets) is blanked on its own. Averages that only
    disagree with their own totals are kept as the page shows them and noted.
  * A table whose separate 100 and 50 columns hold each other's values (rows
    impossible as labelled but not when swapped) is read swapped; a table that
    mixes both orders keeps per row the only reading that fits and blanks the
    pair where both fit. Recorded in parse_note and the page's
    ``milestone_columns`` stat.
  * Thousands separators must be well formed ("1,20" is unreadable).
  * Bare numeric name footnotes ("Kepler Wessels<sup>1</sup>", usually "also
    played for another team; only this country's record is given") are
    stripped from the name and noted.
  * first_year/last_year come from First/Last cells or a Career span. An open
    span ("2025-") leaves last_year blank and sets career_open.
  * best_bowling is the best innings analysis (Best/BBI/BB). A BBM column is
    used only for ODI/T20I lists, where innings and match figures coincide.
  * Bowling strike rate and 4w/5w/10w columns are not carried.

Identity: the name cell's link is followed to its canonical title (redirects
resolved) and kept only when it is a cricketer biography (see is_player_page);
links to list or team pages, disambiguations and namesakes are dropped and
noted. Rows still without a Cricsheet id are matched by name_fallback against
warehouse players of the same team, gender and format.

Extra columns (after the specified ones):
  career_open    '1' when the page gives an open-ended career span.
  wikidata_qid   Wikidata item of the linked article (via the resolver).
  cricinfo_id    ESPNcricinfo player id used for the Cricsheet join.
  id_basis       'link' (title -> Wikidata/ESPNcricinfo -> register), 'name'
                 (name_fallback) or '' when cricsheet_id is blank.
  page_markers   Marker kinds the list page uses ('captain;keeper', 'keeper',
                 ...). A blank captain_marker/keeper_marker means "not marked"
                 only for a kind named here; otherwise the page gives no answer.
  parse_note     '; '-joined notes on anything unread, blanked or inconsistent.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
from lxml import html as lh

from .wiki import Resolver, Wiki, html_tables, title_from_url

FULL_MEMBERS = ["Australia", "England", "South Africa", "India", "New Zealand", "Pakistan",
                "Sri Lanka", "West Indies", "Bangladesh", "Zimbabwe", "Afghanistan", "Ireland"]
ASSOCIATES = ["Scotland", "Netherlands", "United Arab Emirates", "Nepal", "Oman", "Namibia",
              "United States of America", "Canada", "Kenya", "Hong Kong", "Papua New Guinea", "Bermuda"]
FORMATS = ["Test", "ODI", "T20I"]
GENDERS = ["male", "female"]
WIKI_COUNTRY = {"United States of America": ["United States", "United States of America", "USA"],
                "United Arab Emirates": ["United Arab Emirates", "UAE"]}
FORMAT_WORDS = {"Test": ["Test"], "ODI": ["ODI", "One Day International", "One-Day International"],
                "T20I": ["Twenty20 International", "T20I", "Twenty20I"]}
GENDER_WORDS = {"male": [""], "female": ["women ", "women's "]}

COLUMNS = ["country", "gender", "format", "cap", "name", "wikipedia_title", "cricsheet_id",
           "first_year", "last_year", "matches", "innings", "not_outs", "runs", "high_score",
           "bat_avg", "balls_faced", "strike_rate", "hundreds", "fifties", "balls_bowled",
           "maidens", "runs_conceded", "wickets", "best_bowling", "bowl_avg", "economy",
           "catches", "stumpings", "captain_marker", "keeper_marker", "source_page", "revid",
           "career_open", "wikidata_qid", "cricinfo_id", "id_basis", "page_markers", "parse_note"]
INT_FIELDS = {"cap", "matches", "innings", "not_outs", "runs", "balls_faced", "hundreds", "fifties",
              "balls_bowled", "maidens", "runs_conceded", "wickets", "catches", "stumpings"}
DEC_FIELDS = {"bat_avg", "strike_rate", "bowl_avg", "economy"}
MARKERS = "‡†*^#§¶"
_STAT_FIELDS = (INT_FIELDS | DEC_FIELDS | {"high_score", "best_bowling"}) - {"cap", "matches"}


def combos(include_associate_tests: bool = True) -> list[tuple[str, str, str, bool]]:
    """(country, gender, format, in_scope). Associate Tests are out of scope but tried."""
    out = []
    for c in FULL_MEMBERS + ASSOCIATES:
        for g in GENDERS:
            for f in FORMATS:
                scope = c in FULL_MEMBERS or f != "Test"
                if scope or include_associate_tests:
                    out.append((c, g, f, scope))
    return out


def candidate_titles(country: str, gender: str, fmt: str) -> list[str]:
    return [f"List of {c} {g}{f} cricketers" for c in WIKI_COUNTRY.get(country, [country])
            for g in GENDER_WORDS[gender] for f in FORMAT_WORDS[fmt]]


def title_regex(country: str, gender: str, fmt: str) -> re.Pattern:
    """Strict shape of a list title for one (country, gender, format)."""
    cs = "|".join(re.escape(c) for c in WIKI_COUNTRY.get(country, [country]))
    fs = "|".join(re.escape(f) for f in FORMAT_WORDS[fmt])
    gs = r" (?:women|women's)" if gender == "female" else ""
    return re.compile(rf"^List of (?:the )?(?:{cs})(?: national)?{gs} (?:{fs}) cricketers(?: \(.+\))?$")


def _existing(wiki: Wiki, titles: list[str]) -> dict[str, str]:
    """Requested title -> final title, for titles that exist (redirects followed)."""
    out = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        q = wiki.api(action="query", titles="|".join(batch), redirects="1").get("query", {})
        alias = {m["from"]: m["to"] for k in ("normalized", "redirects") for m in q.get(k, [])}
        live = {p["title"] for p in q.get("pages", []) if not p.get("missing") and not p.get("invalid")}
        for t in batch:
            final = t
            for _ in range(4):
                final = alias.get(final, final)
            if final in live:
                out[t] = final
    return out


def _fallback(wiki: Wiki, country: str, gender: str, fmt: str) -> list[str]:
    pat = title_regex(country, gender, fmt)
    hits = []
    for c in WIKI_COUNTRY.get(country, [country])[:1]:
        srsearch = f'intitle:"{c}" intitle:cricketers {FORMAT_WORDS[fmt][0]}'
        if gender == "female":
            srsearch += " women"
        d = wiki.api(action="query", list="search", srsearch=srsearch, srlimit="50")
        hits += [r["title"] for r in d.get("query", {}).get("search", []) if pat.match(r["title"])]
        try:
            nav = wiki.parse(f"Lists of {c} cricketers")
            hits += [t for t in _page_links(nav["html"]) if pat.match(t)]
        except KeyError:
            pass
    return list(dict.fromkeys(hits))


def _page_links(html: str) -> list[str]:
    tree = lh.fromstring(html)
    return [title_from_url(a.get("href")) for a in tree.xpath("//a[starts-with(@href,'/wiki/')]")
            if ":" not in a.get("href")]


def discover(wiki: Wiki, include_associate_tests: bool = True) -> tuple[dict, list]:
    """Map (country, gender, format) -> list of page titles; also return missing combos
    (in-scope only)."""
    todo = combos(include_associate_tests)
    cands = {k[:3]: candidate_titles(*k[:3]) for k in todo}
    exist = _existing(wiki, [t for v in cands.values() for t in v])
    found, missing = {}, []
    for c, g, f, scope in todo:
        titles = list(dict.fromkeys(exist[t] for t in cands[(c, g, f)] if t in exist))
        if not titles and scope:
            hits = _fallback(wiki, c, g, f)
            live = _existing(wiki, hits) if hits else {}
            titles = list(dict.fromkeys(live[t] for t in hits if t in live))
        if titles:
            found[(c, g, f)] = titles
        elif scope:
            missing.append((c, g, f))
    return found, missing


# ---------------------------------------------------------------- parsing
_FOOT = re.compile(r"\[[^\]]*\]")
_SORTKEY = re.compile(r"^\d{10,}♠")
_DASHES = {"", "-", "–", "—", "‒", "−", "n/a", "na", "nan", "none"}
_GROUPS = {"batting", "bowling", "fielding", "general"}
_BOWL_LABELS = {"balls", "b", "mdn", "mdns", "maidens", "wkt", "wkts", "wickets", "w", "best",
                "bbi", "bb", "bbm", "econ", "eco", "er", "economy", "5wi", "5w", "10wm", "4w"}
_BAT_LABELS = {"inn", "inns", "innings", "i", "no", "n/o", "runs", "r", "hs", "100", "100s", "50",
               "50s", "100/50", "bf", "sr"}


def _label(level: str) -> str:
    s = _FOOT.sub("", str(level)).replace("\xa0", " ")
    s = re.sub(r"\.\d+$", "", s.strip()) if re.search(r"[A-Za-z]\.\d+$", s.strip()) else s.strip()
    return re.sub(r"\s+", " ", s).lower()


def map_columns(columns) -> list[str | None]:
    """Output field (or None) for each table column, by label and batting/bowling section."""
    fields: list[str | None] = []
    section, seen = "general", set()
    for idx, col in enumerate(columns):
        levels = [_label(x) for x in (col if isinstance(col, tuple) else (col,))]
        levels = [x for x in levels if x and not x.startswith("unnamed:")]
        group = next((x for x in levels if x in _GROUPS), None)
        names = [x for x in levels if x not in _GROUPS]
        lab = names[-1] if names else ""
        if group in ("batting", "bowling", "fielding"):
            section = group
        elif lab in _BOWL_LABELS:
            section = "bowling"
        elif lab in _BAT_LABELS and section == "general":
            section = "batting"
        elif lab in ("ca", "ct", "c", "catches", "st", "stumpings"):
            section = "fielding"
        f = _field(lab, idx, section, group)
        if f in seen and f in ("runs", "bat_avg"):
            f = {"runs": "runs_conceded", "bat_avg": "bowl_avg"}[f]
        if f in seen:
            f = None
        if f:
            seen.add(f)
        fields.append(f)
    return fields


def _field(lab: str, idx: int, section: str, group: str | None) -> str | None:
    if idx == 0 and lab in {"no", "no.", "number", "s/n", "#", "s.no.", "sr no"}:
        return "cap"
    if "post" not in lab and re.fullmatch(r"(?:test |odi |t20i )?cap(?: no\.?| number)?", lab):
        return "cap"
    if lab in ("name", "player", "players"):
        return "name"
    if lab.startswith("first"):
        return "first"
    if lab.startswith("last"):
        return "last"
    if lab in ("career", "span", "years", "career span"):
        return "span"
    if lab in ("mat", "mats", "matches", "m") and not (lab == "m" and section == "bowling"):
        return "matches"
    if lab in ("inn", "inns", "innings", "i"):
        return "innings"
    if lab in ("no", "n/o", "not outs"):
        return "not_outs"
    if lab in ("runs", "r"):
        return "runs_conceded" if section == "bowling" else "runs"
    if lab in ("hs", "highest", "high score", "highest score"):
        return "high_score"
    if lab in ("avg", "ave", "average", "avg."):
        return "bowl_avg" if section == "bowling" else "bat_avg"
    if lab == "bf":
        return "balls_faced"
    if lab in ("sr", "s/r", "strike rate"):
        return None if section == "bowling" else "strike_rate"
    if lab in ("100", "100s"):
        return "hundreds"
    if lab in ("50", "50s"):
        return "fifties"
    if lab in ("100/50", "100s/50s", "50/100", "50s/100s"):
        return "50/100" if lab.startswith("50") else "100/50"
    if lab in ("balls", "b"):
        return "balls_faced" if group == "batting" else "balls_bowled"
    if lab in ("mdn", "mdns", "maidens") or (lab == "m" and section == "bowling"):
        return "maidens"
    if lab in ("wkt", "wkts", "wickets", "w"):
        return "wickets"
    if lab in ("best", "bbi", "bb", "best bowling"):
        return "best_bowling"
    if lab == "bbm":
        return "bbm"
    if lab in ("econ", "econ.", "eco", "er", "economy"):
        return "economy"
    if lab in ("ca", "ct", "c", "catches"):
        return "catches"
    if lab in ("st", "stumpings"):
        return "stumpings"
    return None


def clean_text(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = _FOOT.sub("", str(v)).replace("\xa0", " ")
    s = _SORTKEY.sub("", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def to_number(v, integer: bool) -> str:
    """Plain number text, '' when blank/dash/unparseable."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if pd.isna(v):
            return ""
        if integer:
            return str(int(v)) if float(v).is_integer() else ""
        return format(float(v), ".10g")
    s = clean_text(v).strip(MARKERS + " {}|")
    if "," in s and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
        return ""  # malformed grouping ("1,20") is a typo, not a number
    s = s.replace(",", "")
    if s.lower() in _DASHES:
        return ""
    if integer:
        return str(int(s)) if re.fullmatch(r"\d+", s) else ""
    return format(float(s), ".10g") if re.fullmatch(r"\d+(?:\.\d+)?|\.\d+", s) else ""


def split_name(v) -> tuple[str, set[str], str]:
    """Name without markers or footnotes; the marker characters found; any bare
    numeric footnote ("Kepler Wessels<sup>1</sup>" -> "1")."""
    s = clean_text(v)
    marks = {ch for ch in s if ch in MARKERS}
    s = re.sub(r"\s+", " ", re.sub(rf"[{re.escape(MARKERS)}]", "", s)).strip(" ,")
    m = re.search(r"(?<=[^\d\s,])\s*(\d+(?:\s*,\s*\d+)*)$", s)
    if m:
        return s[:m.start()].strip(" ,"), marks, re.sub(r"\s+", "", m.group(1))
    return s, marks, ""


def years(first, last, span) -> tuple[str, str, str]:
    """first_year, last_year, career_open."""
    if span is not None:
        s = clean_text(span).replace("—", "–").replace("-", "–")
        ys = re.findall(r"(?<!\d)(\d{4}|\d{2})(?!\d)", s)
        if not ys or len(ys[0]) != 4:
            return "", "", ""
        a = ys[0]
        b = ys[1] if len(ys) > 1 else ""
        if len(b) == 2:
            b = a[:2] + b
        if not b:
            open_ = "–" in s or "present" in s.lower()
            return a, ("" if open_ else a), ("1" if open_ else "")
        return a, b, ""
    fy = re.findall(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)", clean_text(first))
    ly = re.findall(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)", clean_text(last))
    return (fy[0] if fy else ""), (ly[-1] if ly else ""), ""


def _fold(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", re.sub(r"\(.*?\)", "", s or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return {t for t in re.findall(r"[a-z]+", s) if len(t) > 1}


def pick_link(row_links: list, j: int, name: str, aligned: bool) -> str:
    """Article title for the name cell. Positional when the row is aligned with the
    header; otherwise only a link whose title shares a word with the name."""
    cands = [row_links[j]] if j < len(row_links) and row_links[j] else []
    cands += [t for t in row_links if t and t not in cands]
    toks = _fold(name)
    for t in cands:
        if _fold(t) & toks:
            return t
    if aligned and j < len(row_links) and row_links[j]:
        return row_links[j]
    return ""


def parse_legend(html: str) -> dict[str, str]:
    """Marker -> 'captain' | 'keeper' as stated on the page."""
    tree = lh.fromstring(html)
    for bad in tree.xpath("//style|//script|//*[contains(@class,'reflist')]|//*[contains(@class,'navbox')]"):
        bad.getparent().remove(bad)
    text = tree.text_content()
    out = {}
    for m in re.finditer(r"([‡†§¶#*^])\s*(?:[–—\-:=]\s*)?(captain|wicket[- ]?keeper)", text, re.I):
        out.setdefault(m.group(1), "captain" if m.group(2).lower() == "captain" else "keeper")
    return out


def _value(field: str, v) -> tuple[str, bool]:
    """Output value for one cell, and whether a non-blank source value was rejected."""
    raw = clean_text(v)
    blank = raw.replace(",", "").strip(MARKERS + " {}|").lower() in _DASHES
    if field in INT_FIELDS or field in DEC_FIELDS:
        out = to_number(v, field in INT_FIELDS)
    elif field == "high_score" and isinstance(v, (int, float)):  # pandas cast an all-numeric column
        out = to_number(v, True)
    elif field == "high_score":
        s = re.sub(r"\s+", "", raw.replace(",", "")).strip("{}|")
        out = s if re.fullmatch(r"\d+\*?", s) else ""
    elif field == "best_bowling":
        m = re.fullmatch(r"(\d+)[/\-–—](\d+)", re.sub(r"\s+", "", raw).strip("{}|-–—"))
        out = f"{m.group(1)}/{m.group(2)}" if m else ""
    else:
        out = raw
    return out, (not out and not blank)


def _named(col) -> bool:
    levels = [_label(x) for x in (col if isinstance(col, tuple) else (col,))]
    return any(x and not x.startswith("unnamed:") for x in levels)


def _int(row: dict, f: str) -> int | None:
    v = (row.get(f) or "").rstrip("*")
    return int(v) if v.isdigit() else None


def _milestones_ok(h: int | None, f: int | None, hs: int | None, runs: int | None) -> bool:
    """Can `h` hundreds and `f` fifties be true with this highest score and run total?"""
    if h is None or f is None:
        return True
    if hs is not None and ((h > 0 and hs < 100) or (f > 0 and hs < 50)):
        return False
    return runs is None or 100 * h + 50 * f <= runs


def _blank(row: dict, notes: list[str], fields: tuple[str, ...], why: str) -> None:
    notes.append(f"{why}; " + " and ".join(f"{f} {row[f]}" for f in fields) + " blanked")
    for f in fields:
        row[f] = ""


def _checks(row: dict, notes: list[str], fmt: str = "") -> None:
    """Blank values that cannot all be true together, primary counts first, then
    impossible averages; note averages that disagree with their totals."""
    def n(f: str) -> int | None:
        return _int(row, f)

    mat = n("matches")
    max_inn = None if mat is None else 2 * mat if fmt == "Test" else mat
    if n("not_outs") is not None and n("innings") is not None and n("not_outs") > n("innings"):
        _blank(row, notes, ("innings", "not_outs"), "not_outs above innings")
    if n("innings") is not None and max_inn is not None and n("innings") > max_inn:
        _blank(row, notes, ("innings",), f"innings above the possible {max_inn} for {mat} matches")
    if n("high_score") is not None and n("runs") is not None and n("high_score") > n("runs"):
        _blank(row, notes, ("high_score", "runs"), "high_score above runs")
    bound = n("innings") if n("innings") is not None else max_inn
    if None not in (bound, n("high_score"), n("runs")) and n("runs") > bound * n("high_score"):
        _blank(row, notes, ("runs", "high_score"), f"runs above {bound} innings x high_score")
    if not _milestones_ok(n("hundreds"), n("fifties"), n("high_score"), n("runs")):
        _blank(row, notes, ("hundreds", "fifties"), "hundreds/fifties impossible with high_score and runs")
    if n("wickets") is not None and n("balls_bowled") is not None and n("wickets") > n("balls_bowled"):
        _blank(row, notes, ("wickets", "balls_bowled"), "wickets above balls_bowled")
    m = re.fullmatch(r"(\d+)/(\d+)", row.get("best_bowling") or "")
    if m and n("wickets") is not None and int(m.group(1)) > n("wickets"):
        _blank(row, notes, ("best_bowling", "wickets"), "best_bowling wickets above career wickets")
    elif m and n("runs_conceded") is not None and int(m.group(2)) > n("runs_conceded"):
        _blank(row, notes, ("best_bowling", "runs_conceded"), "best_bowling runs above runs_conceded")
    # averages are derived figures: only the average is dropped
    runs, avg = row.get("runs"), row.get("bat_avg")
    if runs and avg:
        r, a = int(runs), float(avg)
        bad = (r > 0 and (a == 0 or a > r)) or (r == 0 and a > 0)
        if not bad and a > 0 and not row.get("innings") and max_inn is not None:
            bad = r / (a + 0.005) > max_inn  # more dismissals than possible innings
        if bad:
            notes.append(f"bat_avg {avg} impossible with {runs} runs, blanked")
            row["bat_avg"] = avg = ""
    if row.get("bowl_avg") and row.get("wickets") == "0":
        notes.append(f"bowl_avg {row['bowl_avg']} impossible with 0 wickets, blanked")
        row["bowl_avg"] = ""
    inn, no = row.get("innings"), row.get("not_outs")
    if runs and avg and inn and no and int(inn) > int(no):
        exp = int(runs) / (int(inn) - int(no))
        if abs(exp - float(avg)) > 0.05:
            notes.append(f"bat_avg {avg} differs from runs/(innings-not_outs) {exp:.2f}")
    rc, w, ba = row.get("runs_conceded"), row.get("wickets"), row.get("bowl_avg")
    if rc and w and ba and int(w) > 0 and abs(int(rc) / int(w) - float(ba)) > 0.05:
        notes.append(f"bowl_avg {ba} differs from runs_conceded/wickets {int(rc) / int(w):.2f}")


def parse_tables(tables, *, fmt: str) -> tuple[list[dict], dict]:
    """Rows (without context columns) from html_tables() output, plus parse stats."""
    rows, stats = [], {"tables": 0, "skipped_rows": 0, "unaligned_rows": 0, "noted_rows": 0,
                       "unparsed": {}}
    for df, links in tables:
        fields = map_columns(df.columns)
        if "name" not in fields or "matches" not in fields:
            continue
        labels = {_label(c[-1] if isinstance(c, tuple) else c) for c in df.columns}
        if labels & {"won", "lost", "win%", "% win"}:
            continue
        stats["tables"] += 1
        has_best = "best_bowling" in fields
        same_len = len(links) == len(df)
        n_named = sum(_named(c) for c in df.columns)
        j_name = fields.index("name")
        k = 0  # link-row cursor when pandas and link rows differ in count
        table_rows = []
        for i in range(len(df)):
            raw = df.iloc[i].tolist()
            vals = {f: v for f, v in zip(fields, raw) if f}
            name, marks, foot = split_name(vals.get("name"))
            cap = to_number(vals.get("cap"), True)
            mat = to_number(vals.get("matches"), True)
            if not name or re.fullmatch(r"(?i)totals?|name|player", name) or not (cap or mat):
                stats["skipped_rows"] += 1
                continue
            row, notes = {"cap": cap, "name": name, "_marks": marks}, []
            if foot:
                notes.append(f"name footnote {foot}")
            row["first_year"], row["last_year"], row["career_open"] = years(
                vals.get("first"), vals.get("last"), vals.get("span") if "span" in vals else None)
            if not row["first_year"] and clean_text(vals.get("first", vals.get("span"))):
                notes.append(f"career years {clean_text(vals.get('first', vals.get('span')))!r} unreadable")
            cells = []  # (column position, field, value, rejected, source text)
            for pos, f in enumerate(fields):
                if f in (None, "name", "cap", "first", "last", "span"):
                    continue
                src = clean_text(raw[pos])
                if f in ("100/50", "50/100"):
                    parts = src.split("/")
                    pair = ("hundreds", "fifties") if f == "100/50" else ("fifties", "hundreds")
                    if len(parts) == 2:
                        cells += [(pos, ff, *_value(ff, pv), src) for ff, pv in zip(pair, parts)]
                    else:
                        cells.append((pos, "hundreds", "", src.lower() not in _DASHES, src))
                    continue
                if f == "bbm":
                    if has_best or fmt == "Test":
                        continue
                    f = "best_bowling"
                cells.append((pos, f, *_value(f, raw[pos]), src))
            for _, f, out, bad, src in cells:
                row[f] = out
                if bad:
                    notes.append(f"{f} {src!r} unreadable")
                    stats["unparsed"][f] = stats["unparsed"].get(f, 0) + 1
            n_cells = len(links[i]) if same_len else None
            if n_cells is not None and n_cells < n_named:
                bad_pos = [c[0] for c in cells if c[3]]
                if bad_pos:
                    p0 = min(bad_pos)
                    for pos, f, *_ in cells:
                        if pos >= p0:
                            row[f] = ""
                    notes.append(f"row has {n_cells} of {n_named} cells; columns from "
                                 f"{p0 + 1} on blanked as shifted")
                elif any(row.get(f) for f in _STAT_FIELDS):
                    notes.append(f"row has {n_cells} of {n_named} cells")
            row["_notes"] = notes
            if same_len:
                aligned = len(links[i]) in (len(df.columns), n_named)
                row["wikipedia_title"] = pick_link(links[i], j_name, name, aligned)
            else:
                aligned, row["wikipedia_title"] = False, ""
                for kk in range(k, min(k + 4, len(links))):
                    t = pick_link(links[kk], j_name, name, False)
                    if t:
                        row["wikipedia_title"], k = t, kk + 1
                        break
            if not aligned:
                stats["unaligned_rows"] += 1
            table_rows.append(row)
        if "hundreds" in fields and "fifties" in fields:
            mode = _orient_milestones(table_rows)
            if mode:
                stats.setdefault("milestone_columns", []).append(mode)
        for row in table_rows:
            notes = row.pop("_notes")
            _checks(row, notes, fmt)
            row["parse_note"] = "; ".join(notes)
            stats["noted_rows"] += bool(notes)
            rows.append(row)
    return rows, stats


def _orient_milestones(rows: list[dict]) -> str:
    """Repair a table whose separate 100 and 50 columns hold each other's values.

    'swapped': at least two rows are impossible as labelled and (almost) none when
    read the other way round, so the whole table is read swapped. 'mixed': both
    readings fail on a comparable number of rows, so each row keeps whichever
    reading alone fits and is blanked when both fit. Rows that fit neither way
    are left to _checks."""
    def fits(r: dict, swap: bool) -> bool:
        h, f = _int(r, "hundreds"), _int(r, "fifties")
        return _milestones_ok(*((f, h) if swap else (h, f)), _int(r, "high_score"), _int(r, "runs"))

    lab = sum(not fits(r, False) for r in rows)
    swp = sum(not fits(r, True) for r in rows)
    if lab < 2:
        return ""
    mode = "swapped" if swp <= lab // 10 else "mixed" if 4 * min(lab, swp) > max(lab, swp) else ""
    for r in rows:
        if not mode or r.get("hundreds") == r.get("fifties"):
            continue
        as_is, other = fits(r, False), fits(r, True)
        if mode == "swapped" or (other and not as_is):
            r["hundreds"], r["fifties"] = r.get("fifties", ""), r.get("hundreds", "")
            r["_notes"].append(f"100 and 50 columns read swapped ({mode} table)")
        elif as_is and other:
            r["_notes"].append(f"hundreds {r['hundreds']} and fifties {r['fifties']} blanked: "
                               "table mixes 100/50 column order")
            r["hundreds"] = r["fifties"] = ""
    return mode


def parse_page(html: str, *, country: str, gender: str, fmt: str, source_page: str,
               revid) -> tuple[list[dict], dict]:
    legend = parse_legend(html)
    rows, stats = parse_tables(html_tables(html), fmt=fmt)
    cap_sym = next((k for k, v in legend.items() if v == "captain"), None)
    wk_sym = next((k for k, v in legend.items() if v == "keeper"), None)
    assumed = []
    used = set().union(*(r["_marks"] for r in rows)) if rows else set()
    if cap_sym is None:
        cap_sym = "‡"
        assumed += ["‡"] if "‡" in used else []
    if wk_sym is None:
        wk_sym = "†"
        assumed += ["†"] if "†" in used else []
    kinds = ";".join(k for k, s in (("captain", cap_sym), ("keeper", wk_sym)) if s in used)
    for r in rows:
        marks = r.pop("_marks")
        r["captain_marker"] = "1" if cap_sym in marks else ""
        r["keeper_marker"] = "1" if wk_sym in marks else ""
        r.update(country=country, gender=gender, format=fmt, source_page=source_page,
                 revid=str(revid or ""), page_markers=kinds)
    stats.update(legend=legend, legend_assumed=assumed, markers_seen=sorted(used))
    return rows, stats


def _sub_pages(html: str, title: str) -> list[str]:
    """Split lists: '<title> (1877-1914)' style pages linked from the main page."""
    return list(dict.fromkeys(t for t in _page_links(html) if t.startswith(title + " (")))


# --------------------------------------------------------------- validation
def cap_checks(df: pd.DataFrame) -> pd.DataFrame:
    """Per list: rows, caps present, duplicate caps, gaps within 1..max."""
    out = []
    for (c, g, f), grp in df.groupby(["country", "gender", "format"], sort=False):
        caps = pd.to_numeric(grp["cap"], errors="coerce").dropna().astype(int)
        dup = sorted(caps[caps.duplicated()].unique().tolist())
        gaps = sorted(set(range(1, int(caps.max()) + 1)) - set(caps)) if len(caps) else []
        out.append({"country": c, "gender": g, "format": f, "rows": len(grp), "caps": len(caps),
                    "min_cap": int(caps.min()) if len(caps) else None,
                    "max_cap": int(caps.max()) if len(caps) else None,
                    "duplicate_caps": dup, "missing_caps": gaps})
    return pd.DataFrame(out)


def appearance_check(df: pd.DataFrame, warehouse: str | Path = "data/warehouse") -> dict:
    """Do resolved players appear in the Cricsheet warehouse for the list's country?

    Only rows whose career reaches the warehouse's first international season for
    that gender and format are checked. Each is classed as: same country, gender
    and format; same country in another format; only other teams (a likely wrong
    identity); or no international appearance at all (coverage gap)."""
    wh = Path(warehouse)
    try:
        players = pd.read_parquet(wh / "players.parquet", columns=["player", "id"])
        matches = pd.read_parquet(wh / "matches.parquet", columns=["match_id", "format", "gender", "team_type", "year"])
        apps = pd.read_parquet(wh / "appearances.parquet", columns=["match_id", "team", "player"])
    except (FileNotFoundError, OSError):
        return {}
    matches = matches[matches["team_type"] == "international"]
    matches = matches.assign(format=matches["format"].replace({"IT20": "T20I"}))
    start = matches.groupby(["gender", "format"])["year"].min().to_dict()
    a = apps.merge(matches, on="match_id").merge(players, on="player")
    a["team"] = a["team"].astype(str)
    exact = set(zip(a["id"], a["team"], a["gender"], a["format"]))
    country = set(zip(a["id"], a["team"]))
    any_team = set(a["id"])
    last = pd.to_numeric(df["last_year"], errors="coerce").fillna(9999)
    first_cov = [start.get((g, f), 9999) for g, f in zip(df["gender"], df["format"])]
    sub = df[(df["cricsheet_id"] != "") & (last >= first_cov)]
    classes = []
    for i, c, g, f in zip(sub["cricsheet_id"], sub["country"], sub["gender"], sub["format"]):
        classes.append("same_format" if (i, c, g, f) in exact else "other_format" if (i, c) in country
                       else "other_team_only" if i in any_team else "no_international")
    sub = sub.assign(check=classes)
    counts = sub["check"].value_counts().to_dict()
    suspect = sub[sub["check"] == "other_team_only"]
    return {"checked": len(sub), **counts,
            "rate_same_country": float(round(sub["check"].isin(["same_format", "other_format"]).mean(), 4)) if len(sub) else None,
            "other_team_only_sample": suspect[["country", "gender", "format", "name", "wikipedia_title",
                                               "cricsheet_id"]].head(20).to_dict("records")}


# --------------------------------------------------------------- identity
PLAYER_RE = re.compile(r"\{\{\s*Infobox cricketer|\[\[Category:[^\]|]*cricketers[\]|]", re.I)
LIST_CATEGORIES = ["Lists of Test cricketers", "Lists of One Day International cricketers",
                   "Lists of Twenty20 International cricketers", "Lists of women Test cricketers",
                   "Lists of women One Day International cricketers",
                   "Lists of women Twenty20 International cricketers"]


def is_player_page(page: dict) -> bool:
    """Is a resolved link target a cricketer biography? List pages, team pages,
    disambiguations and namesakes (no ESPNcricinfo id, no cricketer infobox or
    category) are not."""
    if not page.get("text") or re.match(r"Lists? of ", page.get("title") or ""):
        return False
    return bool(page.get("cricinfo")) or bool(PLAYER_RE.search(page["text"]))


def _name_tokens(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", re.sub(r"\(.*?\)", "", s or ""))
    t = re.findall(r"[a-z]+", "".join(ch for ch in s if not unicodedata.combining(ch)).lower())
    while len(t) > 1 and t[-1] in ("jr", "jnr", "sr", "snr"):
        t.pop()
    return t


def name_fallback(df: pd.DataFrame, warehouse: str | Path, by_cricinfo: dict[int, str]) -> pd.Series:
    """Cricsheet ids for unresolved rows, by name among warehouse players who appeared
    for the same team, gender and format within the row's career years (+-1).

    Accepted only when surname and first initial match exactly one such player whom
    no linked row of the list already holds and no other row claims; a player whose
    register ESPNcricinfo ids exclude the row's own id is refused."""
    wh = Path(warehouse)
    try:
        players = pd.read_parquet(wh / "players.parquet", columns=["player", "id", "name"])
        matches = pd.read_parquet(wh / "matches.parquet", columns=["match_id", "format", "gender", "team_type", "year"])
        apps = pd.read_parquet(wh / "appearances.parquet", columns=["match_id", "team", "player"])
    except (FileNotFoundError, OSError):
        return pd.Series(dtype=str)
    matches = matches[(matches["team_type"] == "international") & matches["format"].isin(FORMATS)]
    a = apps.merge(matches, on="match_id").merge(players, on="player")
    for c in ("team", "gender", "format"):
        a[c] = a[c].astype(str)
    span = a.groupby(["team", "gender", "format", "id", "name"])["year"].agg(["min", "max"]).reset_index()
    pool = {k: list(g.itertuples(index=False)) for k, g in span.groupby(["team", "gender", "format"])}
    cis: dict[str, set[str]] = {}
    for ci, ident in by_cricinfo.items():
        cis.setdefault(ident, set()).add(str(ci))
    held = set(zip(df["country"], df["gender"], df["format"], df["cricsheet_id"]))
    picks = {}
    for i, r in df[(df["cricsheet_id"] == "") & (df["first_year"] != "")].iterrows():
        key, t = (r["country"], r["gender"], r["format"]), _name_tokens(r["name"])
        if len(t) < 2:
            continue
        lo, hi = int(r["first_year"]) - 1, int(r["last_year"] or 9998) + 1
        hits = []
        for c in pool.get(key, []):
            ct = _name_tokens(c.name)
            if (ct and ct[-1] == t[-1] and ct[0][0] == t[0][0] and lo <= c.min and c.max <= hi
                    and key + (c.id,) not in held
                    and not (r["cricinfo_id"] and cis.get(c.id) and r["cricinfo_id"] not in cis[c.id])):
                hits.append(c.id)
        if len(hits) == 1:
            picks[i] = key + (hits[0],)
    claims = Counter(picks.values())
    return pd.Series({i: k[-1] for i, k in picks.items() if claims[k] == 1}, dtype=str)


def unconfigured_lists(wiki: Wiki, covered: list[str]) -> list[str]:
    """Career-list pages in Wikipedia's list categories that this run did not read
    (teams outside FULL_MEMBERS + ASSOCIATES, e.g. World XI or East Africa)."""
    pat = re.compile(r"^List of .+? (?:Test|ODI|One Day International|Twenty20 International) cricketers(?: \(.+\))?$")
    out = set()
    for cat in LIST_CATEGORIES:
        cont: dict = {}
        while True:
            d = wiki.api(action="query", list="categorymembers", cmtitle=f"Category:{cat}", cmlimit="500", **cont)
            out |= {m["title"] for m in d.get("query", {}).get("categorymembers", []) if pat.match(m["title"])}
            if "continue" not in d:
                break
            cont = {"cmcontinue": d["continue"]["cmcontinue"]}
    return sorted(out - set(covered))


# --------------------------------------------------------------------- run
def run(wiki: Wiki, resolver: Resolver, out_dir: str | Path = "data/reference", *,
        warehouse: str | Path = "data/warehouse") -> dict:
    found, missing = discover(wiki)
    rows, pages, failed = [], [], []
    for (c, g, f), titles in found.items():
        queue, done = list(titles), set()
        while queue:
            t = queue.pop(0)
            if t in done:
                continue
            done.add(t)
            try:
                p = wiki.parse(t)
            except KeyError as e:
                failed.append({"page": t, "error": str(e)})
                continue
            queue += [s for s in _sub_pages(p["html"], p["title"]) if s not in done]
            r, st = parse_page(p["html"], country=c, gender=g, fmt=f, source_page=p["title"],
                               revid=p["revid"])
            if not r:
                failed.append({"page": p["title"], "error": "no career table parsed"})
            rows += r
            pages.append({"country": c, "gender": g, "format": f, "page": p["title"],
                          "revid": p["revid"], "rows": len(r), **st})

    seen, uniq = set(), []
    for r in rows:  # a split list's index page may repeat its sub-pages' rows
        key = (r["country"], r["gender"], r["format"], r["cap"], r["name"], r["wikipedia_title"])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    rows = uniq
    titles = sorted({r["wikipedia_title"] for r in rows if r["wikipedia_title"]})
    res = resolver.resolve_titles(titles)
    rejected = set()
    for r in rows:
        t, v = r["wikipedia_title"], res.get(r["wikipedia_title"]) or {}
        if t and not is_player_page(v):
            rejected.add(t)
            note = f"name links to non-player page {v.get('title') or t!r}; link dropped"
            r["parse_note"] = "; ".join(x for x in (r["parse_note"], note) if x)
            r["wikipedia_title"], v = "", {}
        elif t:
            r["wikipedia_title"] = v.get("title") or t  # canonical title (redirects followed)
        r["cricsheet_id"] = v.get("cricsheet_id") or ""
        r["wikidata_qid"] = v.get("qid") or ""
        r["cricinfo_id"] = str(v["cricinfo"]) if v.get("cricinfo") else ""
        r["id_basis"] = "link" if r["cricsheet_id"] else ""
    df = pd.DataFrame(rows).reindex(columns=COLUMNS).fillna("")
    fb = name_fallback(df, warehouse, resolver.by_cricinfo)
    df.loc[fb.index, "cricsheet_id"] = fb
    df.loc[fb.index, "id_basis"] = "name"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "careers_lists.csv", index=False, encoding="utf-8")

    linked = df["wikipedia_title"] != ""
    checks = cap_checks(df)
    return {
        "rows": len(df),
        "lists": len(found),
        "pages": [{k: v for k, v in p.items() if k != "unparsed" or v} for p in pages],
        "missing_combos": missing,
        "unconfigured_lists": unconfigured_lists(wiki, [p["page"] for p in pages]),
        "failed_pages": failed,
        "rejected_links": sorted(rejected),
        "linked_rate": float(round(linked.mean(), 4)) if len(df) else None,
        "cricsheet_match_rate": float(round((df["cricsheet_id"] != "").mean(), 4)) if len(df) else None,
        "cricsheet_match_rate_linked": float(round((df.loc[linked, "cricsheet_id"] != "").mean(), 4)) if linked.any() else None,
        "name_fallback_ids": len(fb),
        "cap_checks": checks.to_dict("records"),
        "appearance_check": appearance_check(df, warehouse),
    }


if __name__ == "__main__":
    import json
    w = Wiki("data/cache/wiki", min_interval=0.5)
    s = run(w, Resolver("data/raw/people.csv", w))
    print(json.dumps({k: v for k, v in s.items() if k not in ("pages", "cap_checks")}, indent=1, default=str))
