"""Current national and franchise squads from Wikipedia.

Cricsheet records who played, not who is still available. This module reads the
current-squad section of each men's and women's national team article and of
each franchise team article (IPL, SA20, BBL, PSL, CPL, WPL, WBBL), so the Best XI
can be limited to contracted or recently selected players instead of everyone
found in match data. When a franchise article has no squad section, the team's
latest season article ("2027 MI Cape Town season") and then the league's season
article ("2026 Caribbean Premier League", Squads) are used. The league season
list also replaces a team-article list that is stale: one dated ("As of 14 August
2025") before that season, or an undated one that shares under 75% of the players
listed for the upcoming season. Players kept from the season list take their
attributes (role, styles, nationality, overseas) from the team article.

role_group uses the role vocabulary ('batter', 'opening batter', 'wicket-keeper',
'wicket-keeper-batter', 'all-rounder', 'bowler', ...); a "Spin bowlers" / "Seam
bowlers" group sets bowling_family when the bowling style does not.

Output data/reference/squads.csv has the columns in COLUMNS. Extra trailing
columns (EXTRA):
  nationality      franchise rows: countries (Cricsheet team names; Caribbean
                   territories -> West Indies) from the nationality column, a flag
                   icon or an "(ENG)"-style code by the name, semicolon-separated
  overseas_basis   how `overseas` was set: 'note' (the row's notes say overseas /
                   international / local, or a code or flag marks only some names),
                   'nationality' (nationality against the league's home country) or ''
  overseas_legend  the page's own wording for the overseas marker, else a short
                   description of which column/marker carried it
  captain          'C' / 'VC' when the row is marked captain or vice-captain in any
                   format (the only captaincy signal on franchise rows)
  shirt_number
  last_test, last_odi, last_t20i   year of last appearance as listed (national rows)
  source_kind      'team article' | 'team season article' | 'league season article'
  title_basis      how wikipedia_title was found: 'link' (the squad table links the
                   player), 'name' (plain-text name whose same-titled article is a
                   cricketer biography; weaker, check before trusting), 'redlink' (the
                   page links a non-existent article), 'non-player link' (the link
                   resolves to a page without a cricketer infobox, e.g. a list of
                   players or a namesake; title left empty) or '' (plain text)
  batting_hand, bowling_class, bowling_family   normalised from the listed styles
  status           notes such as withdrawn / injured / replacement, semicolon-separated
  as_of            date the section says its list is current to ("As of ...",
                   "Updated as on ..."), ISO; '' when not stated
  id_basis         how cricsheet_id was found: 'wikipedia' (title -> Wikidata /
                   {{Cricinfo}} id), 'cricinfo profile' (profile URL in the article),
                   'team name match' (unique name match among players who appeared
                   for that national team or league, with no namesake in the register)
  detail_source    team article the attributes came from when the row is from a
                   season list

The rendered HTML is parsed with lxml rather than wiki.html_tables(): pandas
promotes the first role-group row ("Batters") to a header level and the link
rows skip group rows, so role groups and per-cell links cannot be aligned.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd

from .captains import fallback_cricsheet
from .players import CRICKET_CODES, batting_hand, bowling
from .wiki import Resolver, Wiki, infobox, title_from_url

COLUMNS = ["level", "team", "competition", "gender", "name", "wikipedia_title", "cricsheet_id",
           "role_group", "batting_style", "bowling_style", "forms", "contracted", "captain_formats",
           "vice_captain_formats", "overseas", "domestic_team", "league_teams", "section_title",
           "source_page", "revid", "page_timestamp"]
EXTRA = ["nationality", "overseas_basis", "overseas_legend", "captain", "shirt_number",
         "last_test", "last_odi", "last_t20i", "source_kind", "title_basis",
         "batting_hand", "bowling_class", "bowling_family", "status", "as_of", "id_basis", "detail_source"]

# Cricsheet team name -> article stem
NATIONAL = {c: c for c in [
    "Australia", "England", "South Africa", "India", "New Zealand", "Pakistan", "Sri Lanka",
    "West Indies", "Bangladesh", "Zimbabwe", "Afghanistan", "Ireland", "Scotland", "Netherlands",
    "United Arab Emirates", "Nepal", "Oman", "Namibia", "United States of America", "Canada"]}
NATIONAL["United States of America"] = "United States"

_IPL = ["Chennai Super Kings", "Delhi Capitals", "Gujarat Titans", "Kolkata Knight Riders",
        "Lucknow Super Giants", "Mumbai Indians", "Punjab Kings", "Rajasthan Royals",
        "Royal Challengers Bengaluru", "Sunrisers Hyderabad"]
_BBL = ["Adelaide Strikers", "Brisbane Heat", "Hobart Hurricanes", "Melbourne Renegades",
        "Melbourne Stars", "Perth Scorchers", "Sydney Sixers", "Sydney Thunder"]
_WPL = ["Delhi Capitals", "Gujarat Giants", "Mumbai Indians", "Royal Challengers Bengaluru", "UP Warriorz"]

# season: 'year' -> "2026", 'split' -> "2026–27"; teams: Cricsheet name -> team article
LEAGUES = {
    "Indian Premier League": dict(
        gender="male", home={"India"}, season="year", article="{s} Indian Premier League",
        teams={t: t for t in _IPL}),
    "SA20": dict(
        gender="male", home={"South Africa"}, season="year", article="{s} SA20",
        teams={t: t for t in ["Durban's Super Giants", "Joburg Super Kings", "MI Cape Town",
                              "Paarl Royals", "Pretoria Capitals", "Sunrisers Eastern Cape"]}),
    "Big Bash League": dict(
        gender="male", home={"Australia"}, season="split", article="{s} Big Bash League season",
        teams={t: t for t in _BBL}),
    "Pakistan Super League": dict(
        gender="male", home={"Pakistan"}, season="year", article="{s} Pakistan Super League",
        teams={t: t for t in ["Hyderabad Kingsmen", "Islamabad United", "Karachi Kings",
                              "Lahore Qalandars", "Multan Sultans", "Peshawar Zalmi",
                              "Quetta Gladiators", "Rawalpindiz"]}),
    # CPL locals span many territories, so overseas is taken from notes only
    "Caribbean Premier League": dict(
        gender="male", home=None, season="year", article="{s} Caribbean Premier League",
        teams={"Antigua and Barbuda Falcons": "Antigua & Barbuda Falcons",
               "Barbados Tridents": "Barbados Tridents",
               "Guyana Amazon Warriors": "Guyana Amazon Warriors",
               "Jamaica Kingsmen": "Jamaica Kingsmen",
               "St Kitts and Nevis Patriots": "St Kitts & Nevis Patriots",
               "St Lucia Kings": "Saint Lucia Kings",
               "Trinbago Knight Riders": "Trinbago Knight Riders"}),
    "Women's Premier League": dict(
        gender="female", home={"India"}, season="year", article="{s} Women's Premier League (cricket)",
        teams={t: (t if t == "UP Warriorz" else f"{t} (WPL)") for t in _WPL}),
    "Women's Big Bash League": dict(
        gender="female", home={"Australia"}, season="split",
        article="{s} Women's Big Bash League season",
        teams={t: f"{t} (WBBL)" for t in _BBL}),
}

SQUAD_SECTIONS = [r"current squads?", r"current players", r"current roster", r"squads?",
                  r"teams and squads", r"players", r".*\bsquads?\b.*"]
STOP_HEADING = re.compile(r"former|past|notable|staff|coach|support|development|retired|history"
                          r"|\bcaptains\b|records?\b|statistics|results", re.I)
FORMATS = ("Test", "ODI", "T20I")
_FMT = r"(?:Tests?|ODIs?|T20Is?|T20s?)"
_FMTS = rf"({_FMT}(?:\s*(?:,|/|&|and)\s*{_FMT})*)"
CAPT_RES = [  # group 1: formats, group 2: captain / vice-captain marker
    re.compile(rf"{_FMTS}\s*\(\s*(v\.?\s*c|c)\s*\)", re.I),
    re.compile(rf"{_FMTS}\s+((?:vice[- ]?)?captain)\b", re.I),
    re.compile(rf"((?:vice[- ]?)?captain)\s*\(\s*{_FMTS}\s*\)", re.I),
]
# notes wording; "International Replacement Player" counts, so any "international"
OVERSEAS_RE = re.compile(r"overseas|\binternational\b|foreign|\bimport", re.I)
# page prose; narrower so "Players with international caps ..." is not taken as the legend
LEGEND_RE = re.compile(r"overseas|international (?:signing|player|replacement)|foreign player|\bimport", re.I)
LOCAL_RE = re.compile(r"\blocal\b", re.I)
STATUS = [("withdrawn", r"withdr"), ("injured", r"injur|ruled out"), ("replacement", r"replac"),
          ("unavailable", r"unavailab"), ("released", r"\breleas"), ("pre-signing", r"pre-?sign"),
          ("wildcard", r"wild ?card")]
SKIP_LINKS = {"Captain (cricket)", "Wicket-keeper", "Vice-captain", "Overseas player"}
CODES = {**CRICKET_CODES, "IRL": "Ireland", "MAS": "Malaysia", "JER": "Jersey", "UGA": "Uganda",
         "WIN": "West Indies", "ZAF": "South Africa"}
MARKER_WORDS = {"C", "VC", "WK", "CAPT"}  # "(VC)" is a marker, not a country code
WEST_INDIES = {"Anguilla", "Antigua", "Antigua and Barbuda", "Barbados", "British Virgin Islands",
               "Cricket West Indies", "Dominica", "Grenada", "Guyana", "Jamaica", "Leeward Islands",
               "Montserrat", "Nevis", "Saint Kitts and Nevis", "Saint Lucia", "Saint Martin",
               "Saint Vincent and the Grenadines", "Sint Maarten", "St Kitts and Nevis", "St Lucia",
               "St Vincent and the Grenadines", "Trinidad", "Trinidad and Tobago",
               "United States Virgin Islands", "US Virgin Islands", "Windward Islands"}
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"]
_MON = "|".join(_MONTHS)
AS_OF_RE = re.compile(rf"(?:\bas (?:of|at|on)|\bupdated(?: as)?(?: on| of)?|\bcorrect as of)\s*:?\s*"
                      rf"(\d{{1,2}}\s+(?:{_MON})\s+\d{{4}}|(?:{_MON})\s+\d{{1,2}},?\s+\d{{4}}|(?:{_MON})\s+\d{{4}})",
                      re.I)
_BAT_OK = re.compile(r"hand|bat|left|right", re.I)
_BOWL_OK = re.compile(r"arm|spin|break|orthodox|medium|fast|pace|seam|slow|googly|chinaman|wrist|finger"
                      r"|\boff\b|\bleg\b", re.I)

HEADER_FIELDS = [
    ("name", r"(full )?name|players?( name)?"),
    ("batting_style", r"bat(ting)?( style| hand)?"),
    ("bowling_style", r"bowl(ing)?( style| type)?"),
    ("forms", r"forms?|formats?"),
    ("contract", r"c|con|cc|contract(ed)?( grade)?|central contract|c/g|cg|grade"),
    ("shirt_number", r"s/n|no|jersey( no)?|shirt( no)?|#|number"),
    ("captaincy", r"captain(cy)?|capt"),
    ("role", r"role|position|speciality|specialism"),
    ("notes", r"notes?|additional info|remarks?|info"),
    ("nationality", r"nat|nationality|country|nation|national team"),
    ("last_test", r"last tests?"), ("last_odi", r"last odis?"), ("last_t20i", r"last t20i?s?"),
    ("domestic_team", r"domestic( team| side)?|state( team)?|province|ncl division|(first[- ]class|fc|list a|wncl) team"
                      r"|county|region|zone|club"),
    ("league_team", r".*\b(sa20|bbl|ipl|psl|lpl|bpl|npl|wbbl|wpl|cpl|hundred|franchise|dpl|ilt20|mlc)\b.*|t20 team"),
]
SQUAD_HINT = {"batting_style", "bowling_style", "forms", "shirt_number", "nationality", "contract"}
NOT_SQUAD = {"position", "from", "to", "matches", "mat", "won", "lost", "span", "years", "win%"}


# ---------------------------------------------------------------- cells
def _clean(el):
    el = copy.deepcopy(el)
    for bad in el.xpath(".//style|.//sup[contains(@class,'reference')]|.//*[contains(@class,'sr-only')]"
                        "|.//*[contains(@style,'display:none')]|.//*[contains(@class,'sortkey')]"):
        bad.drop_tree()
    return el


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def cell_text(el) -> str:
    if el is None or "table-na" in (el.get("class") or ""):
        return ""
    for br in el.xpath(".//br"):
        br.tail = "; " + (br.tail or "")
    t = _ws(_clean(el).text_content()).strip(" ;,")
    return "" if re.fullmatch(r"[-–—✗×]*|n/?a", t, re.I) else t


def _href_title(a) -> str | None:
    href = a.get("href") or ""
    if not href.startswith("/wiki/") or ":" in href.split("#")[0][6:]:
        return None
    return title_from_url(href.split("#")[0])


def flag_titles(el) -> list[str]:
    """Article titles linked from a cell (flag icons included)."""
    if el is None:
        return []
    return [t for t in (_href_title(a) for a in el.xpath(".//a[@href]")) if t]


def player_link(el) -> tuple[str, str]:
    """(article title, basis) for a name cell: basis 'link', 'redlink' (the page links a
    non-existent article) or '' (plain text). Flags and (c)/(ENG) markers are skipped."""
    red = False
    for a in _clean(el).xpath(".//a[@href]"):
        if a.xpath("ancestor::*[contains(@class,'flagicon')]") or a.xpath(".//img"):
            continue
        txt = _ws(a.text_content())
        if re.fullmatch(r"[A-Z]{2,4}|c|vc|wk|\W*", txt, re.I):
            continue
        if "new" in (a.get("class") or "").split() or "redlink=1" in (a.get("href") or ""):
            red = True
            continue
        t = _href_title(a)
        if t and t not in SKIP_LINKS:
            return t, "link"
    return "", "redlink" if red else ""


def split_markers(text: str) -> tuple[str, list[str]]:
    """'Moeen Ali (c)' -> ('Moeen Ali', ['c']); '(c, wk)' gives two marks; also strips
    footnote symbols."""
    marks = [_ws(p) for m in re.findall(r"\(\s*([^()]{1,24}?)\s*\)", text) for p in m.split(",") if p.strip()]
    name = re.sub(r"\([^()]*\)", " ", text)
    marks += re.findall(r"[*†‡§¶^#~+]", name)
    name = re.sub(r"[*†‡§¶^#~+]", " ", name)
    return _ws(name).strip(" ,;-"), marks


# --------------------------------------------------------------- vocab
def parse_forms(text: str) -> list[str]:
    got = {re.sub(r"s$", "", f, flags=re.I).upper().replace("TEST", "Test")
           for f in re.findall(_FMT, text or "", flags=re.I)}
    got = {"T20I" if f == "T20" else f for f in got}
    return [f for f in FORMATS if f in got]


def parse_captaincy(text: str) -> tuple[list[str], list[str], str]:
    """'ODI, T20I (C), Test (VC)' -> (['ODI','T20I'], ['Test'], 'C')."""
    c, vc, text = [], [], text or ""
    for i, rx in enumerate(CAPT_RES):
        for m in rx.finditer(text):
            fmts, mark = (m.group(2), m.group(1)) if i == 2 else (m.group(1), m.group(2))
            (vc if mark.lower().startswith("v") else c).extend(parse_forms(fmts))
    c, vc = [f for f in FORMATS if f in c], [f for f in FORMATS if f in vc]
    if c or vc:
        return c, vc, "C" if c else "VC"
    t = (text or "").lower()
    if re.search(r"vice[- ]?capt|\(\s*v\.?\s*c\s*\)|^vc$", t):
        return [], [], "VC"
    if re.search(r"\bcaptain\b|\(\s*c\s*\)|^c$", t):
        return [], [], "C"
    return [], [], ""


def role_group(label: str) -> str:
    """Group heading or role cell -> role vocabulary."""
    s = re.sub(r"[-_]", " ", (label or "").lower())
    if re.search(r"all ?round", s):
        return ("batting all-rounder" if re.search(r"batting all", s) else
                "bowling all-rounder" if re.search(r"bowling all", s) else "all-rounder")
    if re.search(r"wicket ?keep|keeper", s):
        return "wicket-keeper-batter" if re.search(r"\bbat", s) else "wicket-keeper"
    if re.search(r"spin|pace|fast|seam|quick|bowl", s):
        return "bowler"
    if re.search(r"\bopen", s):
        return "opening batter"
    if re.search(r"top order", s):
        return "top-order batter"
    if re.search(r"middle order", s):
        return "middle-order batter"
    if re.search(r"bat", s):
        return "batter"
    return ""


def group_family(label: str) -> str:
    s = (label or "").lower()
    return "spin" if "spin" in s else "pace" if re.search(r"pace|fast|seam|quick", s) else ""


def style_fields(bat: str, bowl: str, family_hint: str = "") -> dict:
    """Listed styles (blanked when the cell holds something else, e.g. a shifted
    team name) plus batting_hand / bowling_class / bowling_family."""
    bat = bat if _BAT_OK.search(bat or "") else ""
    bowl = bowl if _BOWL_OK.search(bowl or "") else ""
    cls, fam, _ = bowling(bowl)
    return {"batting_style": bat, "bowling_style": bowl, "batting_hand": batting_hand(bat),
            "bowling_class": cls, "bowling_family": fam or family_hint}


def status(text: str) -> str:
    return ";".join(k for k, rx in STATUS if re.search(rx, text or "", re.I))


def country(title_or_text: str) -> str:
    s = re.sub(r"( women's| men's)?( national)?( cricket)? team$", "", title_or_text or "").strip()
    s = re.sub(r"\s*\(.*\)$", "", s)
    if s in WEST_INDIES:
        return "West Indies"
    return {"United States": "United States of America", "USA": "United States of America",
            "UAE": "United Arab Emirates"}.get(s, s)


def as_of(html: str) -> str:
    """ISO date (or year-month) the section says its list is current to."""
    m = AS_OF_RE.search(_prose(html))
    if not m:
        return ""
    s = m.group(1).replace(",", "")
    day = re.search(r"\b(\d{1,2})\b", s)
    mon = _MONTHS.index(re.search(_MON, s, re.I).group(0).lower()) + 1
    year = re.search(r"\d{4}", s).group(0)
    return f"{year}-{mon:02d}-{int(day.group(1)):02d}" if day else f"{year}-{mon:02d}"


def _field(header: str) -> str | None:
    h = _ws(header.lower().replace(".", ""))
    for f, pat in HEADER_FIELDS:
        if re.fullmatch(pat, h):
            return f
    return None


def _year(text: str) -> str:
    m = re.search(r"\b(19|20)\d{2}\b", text or "")
    return m.group(0) if m else ""


# --------------------------------------------------------------- tables
def _span(el, attr: str = "colspan") -> int:
    return int(re.sub(r"\D", "", el.get(attr) or "") or 1)


def _grid(table) -> list[tuple[list, list]]:
    """[(physical cells, expanded cells)] per row with colspan/rowspan applied."""
    out, carry = [], {}
    for tr in table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr"):
        phys, row, col = tr.xpath("./td|./th"), [], 0
        queue = list(phys)
        while queue or col in carry:
            if col in carry:
                n, el = carry[col]
                row.append(el)
                carry[col] = (n - 1, el)
                if n - 1 == 0:
                    del carry[col]
                col += 1
                continue
            el = queue.pop(0)
            span, rows = _span(el), _span(el, "rowspan")
            for _ in range(span):
                if rows > 1:
                    carry[col] = (rows - 1, el)
                row.append(el)
                col += 1
        out.append((phys, row))
    return out


def table_rows(table) -> tuple[list[str], list[dict]]:
    """Header names and data rows ({'group': label, 'cells': {header: element}})."""
    header, rows, group = None, [], ""
    for phys, row in _grid(table):
        if not phys:
            continue
        full = [c for c in phys if cell_text(c)]
        if len(full) == 1 and (_span(full[0]) > 1 or len(phys) == 1 and full[0].tag == "th"
                               and full[0].get("scope") != "row"):
            if header is not None:
                group = cell_text(full[0])
            continue
        if all(c.tag == "th" for c in phys) and not any(c.get("scope") == "row" for c in phys):
            names = [cell_text(c) for c in row]
            if header is None:
                header = names
            elif len(header) == len(names) and names != header:  # second header level
                header = [a if a == b or not b else (b if not a else f"{a} {b}")
                          for a, b in zip(header, names)]
            continue
        if header is None:
            continue
        rows.append({"group": group, "cells": {h: (row[i] if i < len(row) else None)
                                               for i, h in enumerate(header) if h}})
    return header or [], rows


def is_squad_table(header: list[str]) -> bool:
    """A per-player squad table, not a coaching-staff or captaincy-record table."""
    fields = {_field(h) for h in header}
    lower = {_ws(h.lower().replace(".", "")) for h in header}
    return "name" in fields and bool(fields & SQUAD_HINT) and not lower & NOT_SQUAD


def _until_stop_heading(html: str) -> str:
    """Drop subsections such as 'Former players' or 'Coaching staff'."""
    for m in re.finditer(r"<h[3-6][^>]*>(.*?)</h[3-6]>", html, flags=re.S):
        if STOP_HEADING.search(re.sub(r"<[^>]+>", "", m.group(1))):
            return html[:m.start()]
    return html


def _tables(html: str):
    from lxml import html as lh
    tree = lh.fromstring(_until_stop_heading(html) or "<div></div>")
    return [t for t in tree.xpath("//table") if not t.xpath(".//table")]


def _prose(html: str) -> str:
    """Section text outside tables and reference lists."""
    from lxml import html as lh
    tree = lh.fromstring(html or "<div></div>")
    for bad in tree.xpath("//style|//table|//sup[contains(@class,'reference')]|//ol[contains(@class,'references')]"
                          "|//div[contains(@class,'reflist')]|//*[contains(@class,'mw-references-wrap')]"):
        bad.drop_tree()
    return _ws(tree.text_content())


def legend(html: str) -> str:
    """Page sentence explaining an overseas marker, if any."""
    for sent in re.split(r"(?<=[.!?])\s+|\s{2,}", _prose(html)):
        if LEGEND_RE.search(sent) and len(sent) < 250:
            return sent.strip()
    return ""


def squad_rows(html: str, *, home: set[str] | None = None) -> list[dict]:
    """Normalised rows from every per-player squad table in a section."""
    out = []
    for table in _tables(html):
        header, rows = table_rows(table)
        if not is_squad_table(header):
            continue
        fields = {h: _field(h) for h in header}
        has_contract = "contract" in fields.values()
        recs, ov_notes = [], set()
        for r in rows:
            cells = {f: [] for f in set(fields.values())}
            for h, el in r["cells"].items():
                cells[fields[h]].append((h, el))
            one = {f: (v[0][1] if v else None) for f, v in cells.items()}
            name_el = one.get("name")
            if name_el is None:
                continue
            name, marks = split_markers(cell_text(name_el))
            if not name or name == r["group"]:
                continue
            notes = " ".join(cell_text(el) for _, el in cells.get("notes", []))
            forms_text = cell_text(one.get("forms"))
            capt = " ".join([cell_text(one.get("captaincy")), notes, " ".join(f"({m})" for m in marks)])
            c, vc, flag = parse_captaincy(capt)
            # some pages mark captaincy in the forms cell: "ODI (C), T20I (C)"; parsed on its
            # own so a "(C)" after the name is not read as captain of every listed format
            fc, fvc, fflag = parse_captaincy(forms_text)
            c = [f for f in FORMATS if f in c or f in fc]
            vc = [f for f in FORMATS if f in vc or f in fvc]
            flag = "C" if "C" in (flag, fflag) else "VC" if "VC" in (flag, fflag) else ""
            nat_el = one.get("nationality")
            nats = [country(t) for t in flag_titles(nat_el)] or (
                [country(cell_text(nat_el))] if cell_text(nat_el) else [])
            nats = list(dict.fromkeys(n for n in nats if n))
            ov, basis = "", ""
            if OVERSEAS_RE.search(notes):
                ov, basis = "1", "note"
                ov_notes.add(OVERSEAS_RE.search(notes).group(0).lower())
            elif LOCAL_RE.search(notes):
                ov, basis = "0", "note"
            league_teams = "; ".join(f"{h}: {cell_text(el)}" for h, el in cells.get("league_team", [])
                                     if cell_text(el))
            contract = cell_text(one.get("contract"))
            title, title_basis = player_link(name_el)
            role = role_group(r["group"]) or role_group(cell_text(one.get("role")))
            if not role and re.fullmatch(r"(?i)\W*(wicket[- ]?keeper|keeper|batter|bowler|all[- ]?rounder)\W*",
                                         notes):
                role = role_group(notes)
            family = group_family(r["group"]) or group_family(cell_text(one.get("role")))
            recs.append({
                "name": name, "wikipedia_title": title, "title_basis": title_basis, "role_group": role,
                **style_fields(cell_text(one.get("batting_style")), cell_text(one.get("bowling_style")), family),
                "status": status(" ".join([notes, " ".join(marks)])),
                "forms": ";".join(parse_forms(forms_text)),
                "contracted": ("1" if contract and not re.fullmatch(r"n|no", contract, re.I) else "0")
                if has_contract else "",
                "captain_formats": ";".join(c), "vice_captain_formats": ";".join(vc), "captain": flag,
                "overseas": ov, "overseas_basis": basis, "overseas_legend": "",
                "nationality": ";".join(nats),
                "domestic_team": "; ".join(dict.fromkeys(cell_text(el) for _, el in cells.get("domestic_team", [])
                                                         if cell_text(el))),
                "league_teams": league_teams,
                "shirt_number": cell_text(one.get("shirt_number")),
                "last_test": _year(cell_text(one.get("last_test"))),
                "last_odi": _year(cell_text(one.get("last_odi"))),
                "last_t20i": _year(cell_text(one.get("last_t20i"))),
            })
        # once a table marks some rows overseas in notes, unmarked rows are local
        if ov_notes:
            leg = "notes column: " + " / ".join(f'"{n}"' for n in sorted(ov_notes)) + " marks overseas"
            for x in recs:
                if not x["overseas_basis"]:
                    x.update(overseas="0", overseas_basis="note")
                x["overseas_legend"] = leg
        elif home:
            for x in recs:
                if not x["overseas_basis"] and x["nationality"]:
                    local = bool(set(x["nationality"].split(";")) & home)
                    x.update(overseas="0" if local else "1", overseas_basis="nationality",
                             overseas_legend="nationality column vs " + "/".join(sorted(home)))
        out.extend(recs)
    return out


def _norm_team(s: str) -> str:
    s = s.lower().replace("&", "and").replace("saint ", "st ")
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def season_team_rows(html: str, team: str, article: str, *, home: set[str] | None = None) -> list[dict]:
    """Players listed under one team's column in a season article's squads table. A
    table may repeat its header row for a second block of teams (2026 PSL)."""
    keys = {_norm_team(team), _norm_team(article)}
    out, kinds = [], set()
    for table in _tables(html):
        cols, seen = [], set()
        for phys, row in _grid(table):
            if phys and all(c.tag == "th" for c in phys):
                cols = [j for j, el in enumerate(row)
                        if _norm_team(cell_text(el)) in keys
                        or any(_norm_team(t) in keys for t in flag_titles(el))]
                continue
            for j in cols:
                el = row[j] if j < len(row) else None
                if el is None or id(el) in seen:
                    continue
                seen.add(id(el))
                for it in el.xpath(".//li") or [el]:
                    for part in _br_split(it):
                        name, marks = split_markers(cell_text(part))
                        if not name:
                            continue
                        _, _, flag = parse_captaincy(" ".join(f"({m})" for m in marks))
                        codes = [m.upper() for m in marks
                                 if re.fullmatch(r"[A-Z]{2,4}", m) and m.upper() not in MARKER_WORDS]
                        flags = [country(t) for t in (_href_title(a) for a in
                                 part.xpath(".//*[contains(@class,'flagicon')]//a[@href]")) if t]
                        kinds |= {"code"} if codes else set()
                        kinds |= {"flag"} if flags else set()
                        nats = [CODES[c] for c in codes if c in CODES] + flags
                        title, title_basis = player_link(part)
                        out.append({"name": name, "wikipedia_title": title, "title_basis": title_basis,
                                    "captain": flag, "captain_formats": "", "vice_captain_formats": "",
                                    "status": status(" ".join(marks)),
                                    "nationality": ";".join(dict.fromkeys(nats)), "_marked": bool(codes or flags),
                                    "overseas": "", "overseas_basis": "", "overseas_legend": ""})
    marked = [r for r in out if r["_marked"]]
    if marked and len(marked) < len(out):  # only some names carry a code/flag: those are overseas
        leg = " / ".join(sorted({"code": "country code after the name, e.g. (ENG)",
                                 "flag": "flag icon before the name"}[k] for k in kinds)) + " marks overseas"
        for r in out:
            r.update(overseas="1" if r["_marked"] else "0", overseas_basis="note", overseas_legend=leg)
    elif marked and home:  # every name is flagged: compare with the league's home country
        for r in out:
            if r["nationality"]:
                local = bool(set(r["nationality"].split(";")) & home)
                r.update(overseas="0" if local else "1", overseas_basis="nationality",
                         overseas_legend="flag/code by the name vs " + "/".join(sorted(home)))
    for r in out:
        del r["_marked"]
    return out


def _br_split(el):
    """Split a cell on <br> into separate fragments (one player each)."""
    from lxml import html as lh
    if not el.xpath(".//br"):
        return [el]
    parts = re.split(r"<br\s*/?>", lh.tostring(el, encoding="unicode"))
    return [lh.fragment_fromstring(p, create_parent="div") for p in parts if p.strip()]


def pick_sections(sections: list[dict], patterns=SQUAD_SECTIONS) -> list[dict]:
    """Candidate squad sections in priority order."""
    out = []
    for pat in patterns:
        for s in sections:
            line = _ws(re.sub(r"<[^>]+>", "", s.get("line", "")))
            if re.fullmatch(pat, line, re.I) and not STOP_HEADING.search(line) and s not in out:
                out.append(s)
    return out


# ---------------------------------------------------------------- fetch
def _existing(wiki: Wiki, titles: list[str]) -> dict[str, str]:
    """Requested title -> canonical title for pages that exist."""
    out = {}
    titles = list(dict.fromkeys(titles))
    for i in range(0, len(titles), 50):
        q = wiki.api(action="query", titles="|".join(titles[i:i + 50]), redirects="1").get("query", {})
        alias = {m["from"]: m["to"] for k in ("normalized", "redirects") for m in q.get(k, [])}
        ok = {p["title"] for p in q.get("pages", []) if not p.get("missing") and not p.get("invalid")}
        for t in titles[i:i + 50]:
            f = t
            for _ in range(3):
                f = alias.get(f, f)
            if f in ok:
                out[t] = f
    return out


def _section_html(wiki: Wiki, title: str, s: dict) -> dict:
    idx = str(s["index"])
    if idx.startswith("T-"):  # transcluded from a template
        return wiki.parse(s["fromtitle"], section=int(idx[2:]))
    return wiki.parse(title, section=int(idx))


def _from_article(wiki: Wiki, title: str, rows_fn) -> tuple[list[dict], dict] | None:
    try:
        secs = wiki.sections(title)
    except KeyError:
        return None
    for s in pick_sections(secs):
        p = _section_html(wiki, title, s)
        rows = rows_fn(p["html"])
        if rows:
            leg = legend(p["html"])
            for r in rows:
                if leg and r.get("overseas_basis"):
                    r["overseas_legend"] = leg
            return rows, {"section_title": _ws(re.sub(r"<[^>]+>", "", s["line"])),
                          "source_page": p["title"], "revid": p["revid"], "as_of": as_of(p["html"])}
    return None


def season_labels(kind: str, today: dt.date) -> list[str]:
    y = today.year
    if kind == "split":
        return [f"{y}–{(y + 1) % 100:02d}", f"{y - 1}–{y % 100:02d}"]
    return [str(y + 1), str(y)]


def national(wiki: Wiki) -> tuple[list[dict], list[str]]:
    rows, failed = [], []
    cands = {}
    for team, stem in NATIONAL.items():
        cands[(team, "male")] = [f"{stem} national cricket team", f"{stem} cricket team",
                                 f"{stem} men's national cricket team"]
        cands[(team, "female")] = [f"{stem} women's national cricket team", f"{stem} women's cricket team"]
    exist = _existing(wiki, [t for v in cands.values() for t in v])
    for (team, gender), titles in cands.items():
        title = next((exist[t] for t in titles if t in exist), None)
        got = _from_article(wiki, title, squad_rows) if title else None
        if not got:
            failed.append(f"{team} ({gender}): {title or 'no article'}: no squad section/table")
            continue
        recs, prov = got
        for r in recs:
            r.update(prov, level="international", team=team, competition="", gender=gender,
                     source_kind="team article", overseas="", overseas_basis="", overseas_legend="",
                     nationality="")
        rows += recs
    return rows, failed


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]+", "", s)


def _keys(r: dict, canon: dict[str, str]) -> set:
    t = r.get("wikipedia_title") or ""
    return ({("t", canon.get(t, t))} if t else set()) | {("n", _norm_name(r["name"]))}


ENRICH = ["role_group", "batting_style", "bowling_style", "batting_hand", "bowling_class", "bowling_family",
          "nationality"]


def choose_roster(team_got, team_kind: str, season_got, season: str, upcoming: str,
                  canon: dict[str, str]) -> tuple[tuple | None, str, dict]:
    """Pick the team-article list or the league season list (see module docstring).
    canon maps linked titles to their redirect targets."""
    if not season_got:
        return team_got, team_kind, ({"source": team_kind} if team_got else {})
    if not team_got:
        return season_got, "league season article", {"source": "league season article", "season": season}
    (t_rows, t_prov), (s_rows, _) = team_got, season_got
    t_keys = [_keys(r, canon) for r in t_rows]
    common = sum(1 for r in s_rows if any(_keys(r, canon) & k for k in t_keys))
    date = t_prov.get("as_of", "")
    check = {"team_list": len(t_rows), "season_list": len(s_rows), "season": season, "common": common,
             "as_of": date}
    if date and int(date[:4]) < int(season[:4]):
        reason = f"team list as of {date} predates the {season} season list"
    elif not date and season == upcoming and common < 0.75 * len(s_rows):
        reason = f"undated team list shares {common}/{len(s_rows)} players with the {season} season list"
    else:
        return team_got, team_kind, {**check, "source": team_kind}
    for r in s_rows:  # player attributes from the team article; captaincy and status stay season-specific
        k = _keys(r, canon)
        t = next((x for x, xk in zip(t_rows, t_keys) if k & xk), None)
        if t is None:
            continue
        if not r.get("wikipedia_title") and t.get("wikipedia_title"):
            r.update(wikipedia_title=t["wikipedia_title"], title_basis=t.get("title_basis", ""))
        for f in ENRICH:
            if not r.get(f) and t.get(f):
                r[f] = t[f]
        if not r.get("overseas") and t.get("overseas"):
            r.update(overseas=t["overseas"], overseas_basis=t.get("overseas_basis", ""),
                     overseas_legend="team article: " + (t.get("overseas_legend") or ""))
        r["detail_source"] = t_prov["source_page"]
    return season_got, "league season article", {**check, "source": "league season article", "reason": reason}


def franchise(wiki: Wiki, today: dt.date | None = None) -> tuple[list[dict], list[str], dict]:
    today = today or dt.date.today()
    rows, failed, checks = [], [], {}
    for comp, cfg in LEAGUES.items():
        seasons = season_labels(cfg["season"], today)
        home = cfg["home"]
        exist = _existing(wiki, list(cfg["teams"].values())
                          + [f"{s} {a} season" for s in seasons for a in cfg["teams"].values()]
                          + [cfg["article"].format(s=s) for s in seasons])
        # a season title can redirect to the league article ("2027 Pakistan Super League")
        season_page = {t: c for t, c in exist.items() if any(s in t and s in c for s in seasons)}
        for team, article in cfg["teams"].items():
            got, kind = None, ""
            if article in exist:
                got, kind = _from_article(wiki, exist[article], lambda h: squad_rows(h, home=home)), "team article"
            for s in seasons if not got else []:
                t = f"{s} {article} season"
                if t in season_page:
                    got, kind = _from_article(wiki, season_page[t], lambda h: squad_rows(h, home=home)), \
                        "team season article"
                    if got:
                        break
            season_got, season = None, ""
            for s in seasons:
                t = cfg["article"].format(s=s)
                if t in season_page:
                    season_got = _from_article(
                        wiki, season_page[t], lambda h: season_team_rows(h, team, article, home=home))
                    if season_got:
                        season = s
                        break
            canon = {}
            if got and season_got:
                canon = _existing(wiki, [r["wikipedia_title"] for r in got[0] + season_got[0]
                                         if r.get("wikipedia_title")])
            got, kind, check = choose_roster(got, kind, season_got, season, seasons[0], canon)
            if not got:
                failed.append(f"{comp}: {team}: no squad section in team, team-season or season article")
                continue
            checks[f"{comp}|{team}"] = check
            recs, prov = got
            for r in recs:
                r.update(prov, level="franchise", team=team, competition=comp, gender=cfg["gender"],
                         source_kind=kind, forms="", contracted="")
            rows += recs
    return rows, failed, checks


def timestamps(wiki: Wiki, revids) -> dict[int, str]:
    revids = sorted({int(r) for r in revids if r})
    out = {}
    for i in range(0, len(revids), 50):
        d = wiki.api(action="query", prop="revisions", rvprop="timestamp|ids",
                     revids="|".join(map(str, revids[i:i + 50])))
        for p in d.get("query", {}).get("pages", []):
            for rv in p.get("revisions", []):
                out[rv["revid"]] = rv["timestamp"]
    return out


# ------------------------------------------------------------ validation
def warehouse_check(df: pd.DataFrame, warehouse: str | Path = "data/warehouse") -> pd.Series:
    """Per row: 'team' if the player has appearances for that team (national: same gender,
    international; franchise: same league), 'league' if only for another team in the league,
    'none' if neither, 'no data' if the warehouse holds no matches for that team/league,
    '' if unresolved."""
    w = Path(warehouse)
    players = pd.read_parquet(w / "players.parquet", columns=["player", "id"])
    apps = pd.read_parquet(w / "appearances.parquet", columns=["match_id", "team", "player"])
    m = pd.read_parquet(w / "matches.parquet", columns=["match_id", "gender", "team_type", "event"])
    a = apps.merge(m, on="match_id").merge(players, on="player")
    a["team"] = a["team"].astype(str)
    intl = set(zip(a.loc[a.team_type == "international", "id"], a["team"][a.team_type == "international"],
                   a.loc[a.team_type == "international", "gender"]))
    club = a[a.team_type == "club"]
    by_team = set(zip(club["id"], club["team"], club["event"], club["gender"]))
    by_league = set(zip(club["id"], club["event"], club["gender"]))
    covered = {(t, g) for _, t, g in intl} | set(zip(club["event"], club["gender"]))
    out = []
    for r in df.itertuples():
        if not r.cricsheet_id:
            out.append("")
        elif (r.team if r.level == "international" else r.competition, r.gender) not in covered:
            out.append("no data")
        elif r.level == "international":
            out.append("team" if (r.cricsheet_id, r.team, r.gender) in intl else "none")
        elif (r.cricsheet_id, r.team, r.competition, r.gender) in by_team:
            out.append("team")
        else:
            out.append("league" if (r.cricsheet_id, r.competition, r.gender) in by_league else "none")
    return pd.Series(out, index=df.index)


# -------------------------------------------------------------------- run
# --------------------------------------------------------------- identity
def _tokens(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.findall(r"[A-Za-z][A-Za-z'-]*", re.sub(r"\s*\(\d+\)$", "", s))


def _name_kind(q: list[str], register_name: str) -> str:
    """'full' (same tokens) or 'initial' ("M Heingo" for "Max Heingo") or ''."""
    r = _tokens(register_name)
    if not r or len(q) < 2:
        return ""
    if [x.lower() for x in q] == [x.lower() for x in r]:
        return "full"
    given = r[:-1]
    if (given and q[-1].lower() == r[-1].lower() and all(g.isupper() and len(g) <= 4 for g in given)
            and q[0][0].lower() == given[0][0].lower()):
        return "initial"
    return ""


def register_counts(people_csv: str | Path) -> Counter:
    """Register people per normalised name (name and unique_name, '(2)' suffix dropped)."""
    p = pd.read_csv(people_csv, dtype=str, usecols=["identifier", "name", "unique_name"]).fillna("")
    return Counter(k for nm, un in zip(p["name"], p["unique_name"])
                   for k in {" ".join(_tokens(n)).lower() for n in (nm, un) if n})


def name_match(name: str, pool: dict[str, str], counts: Counter) -> str:
    """Cricsheet id for a squad name among `pool` ({id: register name} of players who
    appeared for the team or league). Needs exactly one hit, no register namesake,
    and for an initials match no other pool player with that surname."""
    q = _tokens(name)
    hits = {i: k for i, n in pool.items() if (k := _name_kind(q, n))}
    if len(hits) != 1:
        return ""
    i, kind = next(iter(hits.items()))
    if counts[" ".join(_tokens(pool[i])).lower()] > 1:
        return ""
    if kind == "initial" and sum((_tokens(n) or [""])[-1].lower() == q[-1].lower() for n in pool.values()) > 1:
        return ""
    return i


def team_pools(warehouse: str | Path) -> dict:
    """{('international', team, gender) | ('franchise', league, gender): {id: register name}}."""
    w = Path(warehouse)
    players = pd.read_parquet(w / "players.parquet", columns=["player", "id", "name"])
    apps = pd.read_parquet(w / "appearances.parquet", columns=["match_id", "team", "player"])
    m = pd.read_parquet(w / "matches.parquet", columns=["match_id", "gender", "team_type", "event"])
    a = apps.merge(m, on="match_id").merge(players, on="player").drop_duplicates(["id", "team", "event", "gender"])
    pools: dict = {}
    for r in a.itertuples():
        key = ("international", str(r.team), r.gender) if r.team_type == "international" else \
            ("franchise", str(r.event), r.gender)
        pools.setdefault(key, {})[r.id] = r.name
    return pools


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Drop a player listed twice for one team (same Cricsheet id or article)."""
    ident = df["cricsheet_id"].where(df["cricsheet_id"] != "", "t:" + df["wikipedia_title"])
    ident = ident.where(ident != "t:", "row:" + df.index.astype(str))
    return df[~df[["level", "team", "competition", "gender"]].assign(_i=ident).duplicated()]


# -------------------------------------------------------------------- run
def run(wiki: Wiki, resolver: Resolver, out_dir: str | Path = "data/reference", *,
        warehouse: str | Path | None = "data/warehouse", people_csv: str | Path = "data/raw/people.csv",
        today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    nat, nat_failed = national(wiki)
    fr, fr_failed, roster = franchise(wiki, today)
    df = pd.DataFrame(nat + fr)
    for c in COLUMNS + EXTRA:
        if c not in df:
            df[c] = ""
    df = df.fillna("")
    # plain-text names (no link, not a redlink): accept the same-named article only if it
    # is a cricketer biography; recorded as title_basis 'name'
    plain = df["title_basis"] == ""
    by_name = resolver.resolve_titles(df.loc[plain, "name"].unique())
    for i in df.index[plain]:
        p = by_name.get(df.at[i, "name"]) or {}
        if p.get("text") and infobox(p["text"]):
            df.at[i, "wikipedia_title"], df.at[i, "title_basis"] = p["title"], "name"
    titles = [t for t in df["wikipedia_title"].unique() if t]
    ids = resolver.resolve_titles(titles)
    # squad tables sometimes link a redirect to a list/team page or a namesake's article
    not_player = {t for t, p in ids.items() if not infobox(p.get("text"))}
    bad = df["wikipedia_title"].isin(not_player)
    df.loc[bad, "title_basis"] = "non-player link"
    df.loc[bad, "wikipedia_title"] = ""
    people_ok = Path(people_csv).exists()
    if people_ok:  # biographies without a Wikidata / {{Cricinfo}} id: profile URL in the text
        cs_name = pd.read_csv(people_csv, dtype=str, usecols=["identifier", "name"]).fillna("")
        cs_name = dict(zip(cs_name["identifier"], cs_name["name"]))
        for t, p in ids.items():
            if t not in not_player and not p.get("cricsheet_id") and not p.get("cricinfo"):
                fid = fallback_cricsheet(p, resolver.by_cricinfo, cs_name)
                if fid:
                    p.update(cricsheet_id=fid, id_basis="cricinfo profile")
    df["cricsheet_id"] = df["wikipedia_title"].map(lambda t: (ids.get(t) or {}).get("cricsheet_id") or "")
    df["id_basis"] = [((ids.get(t) or {}).get("id_basis") or "wikipedia") if c else ""
                      for t, c in zip(df["wikipedia_title"], df["cricsheet_id"])]
    df["wikipedia_title"] = df["wikipedia_title"].map(lambda t: (ids.get(t) or {}).get("title") or t if t else "")
    if warehouse and people_ok and Path(warehouse, "appearances.parquet").exists():
        pools, counts = team_pools(warehouse), register_counts(people_csv)
        for i in df.index[df["cricsheet_id"] == ""]:
            r = df.loc[i]
            key = (r["level"], r["team"] if r["level"] == "international" else r["competition"], r["gender"])
            cid = name_match(r["name"], pools.get(key, {}), counts)
            if cid:
                df.at[i, "cricsheet_id"], df.at[i, "id_basis"] = cid, "team name match"
    n_before = len(df)
    df = dedupe(df)
    ts = timestamps(wiki, [r for r in df["revid"].unique() if r not in ("", None)])
    df["page_timestamp"] = df["revid"].map(lambda r: ts.get(int(r), "") if r not in ("", None) else "")
    df["revid"] = df["revid"].map(lambda r: str(int(r)) if r not in ("", None) else "")
    df = df[COLUMNS + EXTRA].fillna("").astype(str)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "squads.csv", index=False, encoding="utf-8")

    linked = df["wikipedia_title"] != ""
    summary = {
        "rows": len(df),
        "teams": int(df.groupby(["level", "team", "competition", "gender"]).ngroups),
        "per_team": {f"{k[0]}|{k[1]}|{k[2] or '-'}|{k[3]}": int(v)
                     for k, v in df.groupby(["level", "team", "competition", "gender"]).size().items()},
        "linked_share": round(float(linked.mean()), 4) if len(df) else 0.0,
        "cricsheet_match_rate": round(float((df["cricsheet_id"] != "").mean()), 4) if len(df) else 0.0,
        "cricsheet_match_rate_linked": round(float((df.loc[linked, "cricsheet_id"] != "").mean()), 4)
        if linked.any() else 0.0,
        "title_basis": df["title_basis"].value_counts().to_dict(),
        "source_kind": df.drop_duplicates(["level", "team", "competition", "gender"])["source_kind"]
        .value_counts().to_dict(),
        "failed": nat_failed + fr_failed,
        "duplicates_dropped": n_before - len(df),
        "id_basis": df.loc[df["cricsheet_id"] != "", "id_basis"].value_counts().to_dict(),
        "status": df["status"].str.split(";").explode().loc[lambda s: s != ""].value_counts().to_dict(),
        # lists the page itself dates more than a year back
        "stale_as_of": sorted({f"{r.team}|{r.competition or '-'}|{r.gender}: {r.as_of}"
                               for r in df[df["as_of"] != ""].itertuples()
                               if r.as_of[:7] < (today - dt.timedelta(days=365)).isoformat()[:7]}),
        "roster_check": roster,
        "captains": {},
    }
    for r in df[(df.level == "international") & (df.captain != "")].itertuples():
        summary["captains"].setdefault(f"{r.team} ({r.gender})", []).append(
            f"{r.name}: C={r.captain_formats or '-'} VC={r.vice_captain_formats or '-'} ({r.captain})")
    if warehouse and Path(warehouse, "appearances.parquet").exists():
        chk = warehouse_check(df, warehouse)
        res = chk[chk.isin(["team", "league", "none"])]

        def share(s: pd.Series) -> float:
            return round(float(s.isin(["team", "league"]).mean()), 4) if len(s) else 0.0

        summary["appearance_check"] = {
            "counts": chk[chk != ""].value_counts().to_dict(),
            "no_data_teams": sorted({f"{r.team or r.competition} ({r.gender})"
                                     for r in df[chk == "no data"].itertuples()}),
            "team_share": round(float((res == "team").mean()), 4) if len(res) else 0.0,
            "team_or_league_share": share(res),
            "by_level": {lvl: share(res[df.loc[res.index, "level"] == lvl])
                         for lvl in ("international", "franchise")},
            "by_title_basis": {b: share(res[df.loc[res.index, "title_basis"] == b])
                               for b in ("link", "name")},
        }
    return summary
