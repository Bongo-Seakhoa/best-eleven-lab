"""Per-player attributes from English Wikipedia {{Infobox cricketer}}.

Candidates are Cricsheet people who appear in the warehouse appearances table and
whose ESPNcricinfo id (key_cricinfo / _2 / _3) maps through Wikidata P2697 to an
enwiki article, plus every ``wikipedia_title`` listed in careers_lists.csv,
captains.csv or squads.csv under out_dir (historic or squad players who may have
no Cricsheet id). Output is data/reference/players_wiki.csv with one row per
(article, Cricsheet id); an article linked to two Cricsheet ids yields two rows.

Identity: an extra title with no Wikidata/{{Cricinfo}} id may take one from the
article's own ESPNcricinfo profile links. A cricsheet_id is left empty when the
register's names for it cannot name the article's subject (Wikidata or register
errors), or when one Cricsheet id would name two articles (register conflations).
Lists and disambiguation pages reached through redirects are skipped.

Conventions:
- country, international_span and the *_cap columns list each national side in
  infobox order (country, country2, country3) separated by '; '.
- active_international is '1' if any international span ends in 'present', '0'
  if spans exist and all end in a year, else ''.
- Retirement flags need an explicit statement whose subject is the player
  (name or pronoun, not another person named nearer the verb). A report of
  retirement from international cricket, or from all cricket ("all forms of
  cricket", "the game"; not bare "professional cricket", which county players
  use while still playing for associate nations), sets retired_international and
  all three format flags. A report of coming out of retirement clears the formats
  it names, or undoes the international retirement in effect when it names none.
  Events are ordered by the year nearest their phrase (a season "2010-11" counts as
  its end year), then by article position. Retirement from a role (captaincy,
  umpiring), someone else's retirement ("the retirement ... of Justin Langer",
  "Simpson ... announced that he would retire") and wishes, denials or rumours
  are ignored. An infobox appearance in a later year than an international
  retirement undoes it like a come-back; a format flag is likewise dropped when
  that format was played after the statement. Evidence quotes the latest statement.

Extra columns (after the specified ones):
- death_date: ISO date from {{Death date ...}} when present.
- gender: 'female' when the infobox sets female=, or a "women ... cricketers"
  category is present; 'male' when only other "cricketers" categories are present.
- has_infobox: '1' when an {{Infobox cricketer}} was found, else '0'.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import pandas as pd

from .wiki import Resolver, Wiki, infobox, strip_markup

COLUMNS = ["wikipedia_title", "revid", "qid", "cricinfo_id", "cricsheet_id", "full_name", "birth_date",
           "country", "batting_hand", "bowling_style_raw", "bowling_class", "bowling_family", "bowling_arm",
           "role_raw", "role", "international_span", "active_international", "last_test_year",
           "last_odi_year", "last_t20i_year", "test_cap", "odi_cap", "t20i_cap", "retired_test",
           "retired_odi", "retired_t20i", "retired_international", "retirement_evidence", "stats_as_of",
           "career_json"]
EXTRA_COLUMNS = ["death_date", "gender", "has_infobox"]
REFERENCE_LISTS = ("careers_lists.csv", "captains.csv", "squads.csv")

CRICKET_CODES = {
    "AUS": "Australia", "ENG": "England", "RSA": "South Africa", "SA": "South Africa", "IND": "India",
    "NZ": "New Zealand", "NZL": "New Zealand", "PAK": "Pakistan", "SL": "Sri Lanka", "SRI": "Sri Lanka",
    "WI": "West Indies", "BAN": "Bangladesh", "ZIM": "Zimbabwe", "AFG": "Afghanistan", "IRE": "Ireland",
    "SCO": "Scotland", "NED": "Netherlands", "UAE": "United Arab Emirates", "NEP": "Nepal", "OMA": "Oman",
    "OMN": "Oman", "NAM": "Namibia", "USA": "United States of America", "CAN": "Canada", "KEN": "Kenya",
    "HK": "Hong Kong", "HKG": "Hong Kong", "PNG": "Papua New Guinea"}
COUNTRY_ALIASES = {
    "united states": "United States of America", "usa": "United States of America",
    "u.s.a.": "United States of America", "us": "United States of America",
    "uae": "United Arab Emirates", "u.a.e.": "United Arab Emirates", "holland": "Netherlands",
    "the netherlands": "Netherlands", "png": "Papua New Guinea", "hong kong, china": "Hong Kong",
    "bharat": "India", "gujrat": "India", "gujarat": "India", "south african": "South Africa",
    "world xi": "ICC World XI", "rest of the world xi": "ICC World XI"}
# Case/spacing variants seen in infoboxes ("india", "srilanka") map to these spellings.
_CANON = {re.sub(r"\s+", "", c.lower()): c for c in list(CRICKET_CODES.values()) + ["ICC World XI"]}
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}


# ------------------------------------------------------------- value helpers
def _plain(value: str | None) -> str:
    """strip_markup plus the dash and flag/country templates that it would drop."""
    if not value:
        return ""
    s = re.sub(r"\{\{\s*(?:ndash|snd|spaced ndash|mdash|–)\s*\}\}|&ndash;|&mdash;", "-", value, flags=re.I)
    s = re.sub(r"\{\{\s*flag(?:icon|deco)\s*\|[^{}]*\}\}", "", s, flags=re.I)
    s = re.sub(r"\{\{\s*(?:cr|cricon|crw|cr-rt|flagcricket)\s*\|\s*([A-Za-z]+)[^{}]*\}\}",
               lambda m: CRICKET_CODES.get(m.group(1).upper(), m.group(1)), s, flags=re.I)
    s = re.sub(r"\{\{\s*flag\s*\|\s*([^{}|]+)[^{}]*\}\}", r"\1", s, flags=re.I)
    return strip_markup(s).replace("—", "-")


def _truthy(value: str | None) -> bool:
    v = _plain(value).lower()
    return bool(v) and v not in ("no", "n", "false", "0")


def _year(value: str | None) -> str:
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", _plain(value))
    return m.group(1) if m else ""


def _num(value: str | None):
    s = _plain(value).replace(",", "").strip()
    m = re.match(r"\d+(?:\.\d+)?", s)
    if not m:
        return None
    return float(m.group()) if "." in m.group() else int(m.group())


def _pair(value: str | None) -> tuple:
    parts = re.split(r"\s*/\s*", _plain(value), maxsplit=1)
    return _num(parts[0]), _num(parts[1]) if len(parts) > 1 else None


def _iso(y, m, d) -> str:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except (TypeError, ValueError):
        return ""


def parse_date(value: str | None, kind: str = "birth") -> str:
    """ISO date from {{Birth date and age|y|m|d}} style templates or a plain date."""
    if not value:
        return ""
    rx = (r"\{\{\s*(?:%s[ _-]?date(?:[ _-]and[ _-]age)?|%s)\s*\|([^{}]*)\}\}"
          % (kind, "bda|dob|b-da" if kind == "birth" else "dda|d-da"))
    m = re.search(rx, value, flags=re.I)
    if m:
        args = [a.strip() for a in m.group(1).split("|") if "=" not in a and a.strip()]
        nums = [a for a in args if a.isdigit()]
        if len(nums) >= 3:
            return _iso(*nums[:3])
        if args:
            return _plain_date(args[0])
        return ""
    return _plain_date(_plain(value))


def _plain_date(s: str) -> str:
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b", s)
    if m and m.group(2).lower() in MONTHS:
        return _iso(m.group(3), MONTHS[m.group(2).lower()], m.group(1))
    m = re.search(r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", s)
    if m and m.group(1).lower() in MONTHS:
        return _iso(m.group(3), MONTHS[m.group(1).lower()], m.group(2))
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    return _iso(*m.groups()) if m else ""


def country_name(value: str | None) -> str:
    s = re.sub(r"\s*\([^()]*\)$|(?<=[a-z])\d+$", "", _plain(value)).strip()  # "India(Assam)", "India1"
    return COUNTRY_ALIASES.get(s.lower()) or _CANON.get(re.sub(r"\s+", "", s.lower()), s)


# --------------------------------------------------------------- normalisers
def batting_hand(raw: str | None) -> str:
    m = re.search(r"\b(left|right)", (raw or "").lower())
    return m.group(1) if m else ""


def _bowling_segment(seg: str) -> tuple[str, str, str]:
    t = re.sub(r"\s+", " ", re.sub(r"[-–—_]", " ", seg.lower())).strip()
    arm = "left" if re.search(r"\bleft ?(?:arm|hand)", t) else "right" if re.search(r"\bright ?(?:arm|hand)", t) else ""
    if re.search(r"chinaman|unorthodox", t):
        return "LWS", "spin", "left"
    if re.search(r"wrist|\bleg ?(?:break|spin)|googly", t):
        return ("LWS", "spin", "left") if arm == "left" else ("LB", "spin", "right")
    if re.search(r"orthodox|slow left", t):
        return "SLA", "spin", "left"
    if re.search(r"\boff ?(?:break|spin)|finger spin", t):
        return ("SLA", "spin", "left") if arm == "left" else ("OB", "spin", "right")
    if re.search(r"\bspin", t):
        return ("SLA", "spin", "left") if arm == "left" else ("", "spin", arm)
    for rx, speed in ((r"fast medium", "FM"), (r"medium fast", "MF"), (r"slow medium|medium slow", "M"),
                      (r"\bmedium", "M"), (r"\bfast", "F")):
        if re.search(rx, t):
            return ((arm[0].upper() + speed) if arm else ""), "pace", arm
    if re.search(r"\b(?:pace|seam)", t):
        return "", "pace", arm
    return "", "", arm


def bowling(raw: str | None) -> tuple[str, str, str]:
    """(bowling_class, bowling_family, bowling_arm) from the first listed style."""
    segs = [s for s in re.split(r"\s*(?:,|;|/|\n|\band\b|\bor\b)\s*", raw or "") if s.strip()]
    arm = ""
    for seg in segs:
        cls, fam, a = _bowling_segment(seg)
        if cls or fam:
            return cls, fam, a or arm
        arm = arm or a
    return "", "", arm


def role(raw: str | None) -> str:
    t = re.sub(r"\s+", " ", re.sub(r"[-–_]", " ", (raw or "").lower()))
    keep = [p for p in re.split(r"\s*(?:,|;|/|&|\band\b|\n)\s*", t)
            if p and not re.match(r"(?:occasional(?:ly)?|part time|sometimes?)\b", p)]
    t = " ".join(keep)
    keeper = re.search(r"wicket ?keep|\bkeeper", t)
    bat = re.search(r"\bbat(?:ter|sman|smen|swoman|ting|s)?\b|\bopener\b(?! bowl)", t)
    if keeper:
        return "wicket-keeper-batter" if bat else "wicket-keeper"
    if re.search(r"bat(?:ting|ter|sman) all ?rounder", t):
        return "batting all-rounder"
    if re.search(r"bowl(?:ing|er) all ?rounder", t):
        return "bowling all-rounder"
    if re.search(r"all ?rounder", t):
        return "all-rounder"
    if re.search(r"\bopen(?:ing|er)\b(?! bowl)", t):
        return "opening batter"
    if re.search(r"top order", t):
        return "top-order batter"
    if re.search(r"middle order", t):
        return "middle-order batter"
    if bat:
        return "batter"
    if re.search(r"\bbowler|\bspinner|\bseamer|\bpacer", t):
        return "bowler"
    return ""


# ------------------------------------------------------------------ infobox
_COLS = {"test": "Test", "tests": "Test", "testcricket": "Test", "odi": "ODI", "odis": "ODI",
         "onedayinternational": "ODI", "onedayinternationals": "ODI", "t20i": "T20I", "t20is": "T20I",
         "twenty20international": "T20I", "twenty20internationals": "T20I", "t20international": "T20I",
         "fc": "FC", "firstclass": "FC", "firstclasscricket": "FC", "la": "LA", "lista": "LA",
         "listacricket": "LA", "t20": "T20", "t20s": "T20", "twenty20": "T20", "t20cricket": "T20"}


def column_key(label: str, female: bool = False) -> str:
    m = re.search(r"\[\[([^|\]]*)", label)
    target = (m.group(1) if m else "").lower()
    k = re.sub(r"[^a-z0-9]", "", _plain(label).lower())
    women = female or "women" in target
    for prefix in ("womens", "women", "w"):
        if k.startswith(prefix) and k[len(prefix):] in _COLS:
            k, women = k[len(prefix):], True
            break
    base = _COLS.get(k)
    if base is None:
        return "other"
    return "W" + base if women and base in ("Test", "ODI", "T20I") else base


def career(ib: dict[str, str], female: bool = False) -> dict:
    out: dict[str, dict] = {}
    idx = sorted(int(k[6:]) for k in ib if re.fullmatch(r"column\d+", k))
    for i in idx:
        label = ib.get(f"column{i}", "")
        if not _plain(label):
            continue
        key = column_key(label, female)
        rec = {"matches": _num(ib.get(f"matches{i}")), "runs": _num(ib.get(f"runs{i}")),
               "bat_avg": _num(ib.get(f"bat avg{i}"))}
        rec["hundreds"], rec["fifties"] = _pair(ib.get(f"100s/50s{i}"))
        ts = _plain(ib.get(f"top score{i}"))
        rec["top_score"] = _num(ts.replace("*", ""))
        rec["not_out"] = ("*" in ts) if rec["top_score"] is not None else None
        rec.update(balls=_num(ib.get(f"deliveries{i}")), wickets=_num(ib.get(f"wickets{i}")),
                   bowl_avg=_num(ib.get(f"bowl avg{i}")), five_w=_num(ib.get(f"fivefor{i}")),
                   ten_w=_num(ib.get(f"tenfor{i}")))
        best = _plain(ib.get(f"best bowling{i}")).replace(" ", "")
        rec["best"] = best if re.search(r"\d", best) else None
        rec["catches"], rec["stumpings"] = _pair(ib.get(f"catches/stumpings{i}"))
        if key == "other":
            rec["label"] = _plain(label)
        n, base = 2, key
        while key in out:
            key, n = f"{base}_{n}", n + 1
        out[key] = rec
    return out


def _without_refs(text: str) -> str:
    s = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s)
    return re.sub(r"<ref(?:\s[^>]*)?>.*?</ref>", "", s, flags=re.S | re.I)


def cricketer_infobox(text: str | None) -> dict[str, str]:
    """Infobox cricketer fields. When it is embedded in another infobox (e.g.
    officeholder), personal fields missing from it are taken from the host."""
    if not text:
        return {}
    s = re.sub(r"\{\{\s*Infobox[ _]+cricketer", "{{Infobox cricketer", _without_refs(text), flags=re.I)
    ib = infobox(s)
    if ib and _truthy(ib.get("embed")):
        host = infobox(s, "Infobox")
        for k in ("birth_date", "death_date", "full_name"):
            if not ib.get(k) and host.get(k):
                ib[k] = host[k]
    return ib


def _spans(ib: dict[str, str]) -> list[str]:
    out = []
    for k in ("internationalspan", "internationalspan2", "internationalspan3"):
        s = re.sub(r"\s*-\s*", "-", _plain(ib.get(k)))
        if s:
            out.append(s)
    return out


def active_international(spans: list[str]) -> str:
    states = []
    for s in spans:
        s = s.lower().rstrip(" )")
        if s.endswith("present"):
            states.append("1")
        elif re.search(r"\d{2,4}$", s):
            states.append("0")
    return "1" if "1" in states else "0" if states else ""


def _last_year(ib: dict[str, str], fmt: str) -> str:
    y = _year(ib.get(f"last{fmt}year")) or _year(ib.get(f"last{fmt}date"))
    if not y and ib.get(f"one{fmt}"):
        y = _year(ib.get(f"{fmt}debutyear")) or _year(ib.get(f"{fmt}debutdate"))
    return y


def _caps(ib: dict[str, str], fmt: str) -> str:
    caps = []
    for k in (f"{fmt}cap", f"{fmt}cap2"):
        m = re.search(r"\d+", _plain(ib.get(k)))
        if m:
            caps.append(m.group())
    return "; ".join(caps)


def gender(ib: dict[str, str], text: str) -> str:
    if _truthy(ib.get("female")):
        return "female"
    cats = re.findall(r"\[\[\s*Category\s*:\s*([^\]|]+)", text or "", flags=re.I)
    if any(re.search(r"\bwomen\b.*\bcricketers\b", c, re.I) for c in cats):
        return "female"
    if any(re.search(r"\bcricketers\b", c, re.I) for c in cats):
        return "male"
    return ""


# ---------------------------------------------------------- article prose
_DROP_SECTIONS = re.compile(r"(?:references|external links|further reading|see also|notes|bibliography|"
                            r"sources|citations|footnotes)$", re.I)
_TPL_KEEP_FIRST = {"nowrap", "nobr", "small", "abbr", "sort", "noitalic", "nowrap begin", "big", "em"}


def _template(m: re.Match) -> str:
    parts = m.group(1).split("|")
    name = parts[0].strip().lower().replace("_", " ")
    pos = [p.strip() for p in parts[1:] if "=" not in p]
    if name in _TPL_KEEP_FIRST and pos:
        return pos[0]
    if name == "lang" and len(pos) > 1:
        return pos[1]
    if name == "sortname" and len(pos) > 1:
        return f"{pos[0]} {pos[1]}"
    if name in ("cr", "cricon", "crw", "cr-rt", "flagcricket") and pos:
        return CRICKET_CODES.get(pos[0].upper(), pos[0])
    if name in ("ndash", "snd", "mdash", "–"):
        return "-"
    if name in ("nbsp", "sp"):
        return " "
    return ""


def _drop_bracketed(s: str, opener: re.Pattern) -> str:
    out, i = [], 0
    for m in opener.finditer(s):
        if m.start() < i:
            continue
        out.append(s[i:m.start()])
        j, depth = m.start(), 0
        while j < len(s):
            if s.startswith("[[", j):
                depth += 1; j += 2; continue
            if s.startswith("]]", j):
                depth -= 1; j += 2
                if depth == 0:
                    break
                continue
            j += 1
        i = j
    out.append(s[i:])
    return "".join(out)


def _prose(text: str) -> str:
    s = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<ref(?:\s[^>]*)?>.*?</ref>", "", s, flags=re.S | re.I)
    s = re.sub(r"<(gallery|math|timeline|syntaxhighlight|score|imagemap|chem)\b[^>]*>.*?</\1>", "", s,
               flags=re.S | re.I)
    s = _drop_bracketed(s, re.compile(r"\[\[\s*(?:File|Image)\s*:", re.I))
    s = re.sub(r"\[\[\s*Category\s*:[^\]]*\]\]", "", s, flags=re.I)
    s = re.sub(r"\[\[([^\[\]|]*)\|([^\[\]]*)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\[\]|]*)\]\]", r"\1", s)
    for _ in range(40):  # innermost templates first
        s, n = re.subn(r"\{\{([^{}]*)\}\}", _template, s)
        if not n:
            break
    lines, depth = [], 0
    for line in s.split("\n"):  # drop wikitables
        st = line.lstrip()
        if st.startswith("{|"):
            depth += 1
        if depth:
            if st.startswith("|}"):
                depth -= 1
            continue
        lines.append(line)
    s = "\n".join(lines)
    s = re.sub(r"\[(?:https?:)?//[^\s\]]+\s*([^\]]*)\]", r"\1", s)
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"'{2,}", "", s)
    s = (s.replace("&nbsp;", " ").replace("&ndash;", "-").replace("&mdash;", "-").replace("&amp;", "&")
         .replace("–", "-").replace("—", "-").replace(" ", " "))
    return s


_ABBREV = {"mr", "mrs", "ms", "dr", "st", "no", "vs", "v", "jr", "sr", "lt", "capt", "col", "gen", "rev",
           "prof", "mt", "ft", "etc", "approx", "inc", "ltd", "co"}


def _split_sentences(par: str) -> list[str]:
    out, start = [], 0
    for m in re.finditer(r"[.!?][\"”’')]*\s+(?=[\"“'(]?[A-Z0-9])", par):
        head = par[start:m.start()].rsplit(None, 1)
        tok = head[-1].rstrip(".").split(".")[-1] if head else ""
        if (len(tok) == 1 and tok.isupper()) or tok.lower() in _ABBREV:
            continue
        out.append(par[start:m.end()].strip())
        start = m.end()
    out.append(par[start:].strip())
    return [s for s in out if s]


def article_sentences(text: str | None) -> list[str]:
    """Plain-text sentences of the article body (infobox, tables, refs and
    reference sections removed)."""
    if not text:
        return []
    out, drop = [], 0
    for line in _prose(text).split("\n"):
        h = re.match(r"^\s*(=+)\s*(.*?)\s*\1\s*$", line)
        if h:
            level = len(h.group(1))
            if drop and level <= drop:
                drop = 0
            if not drop and _DROP_SECTIONS.match(h.group(2).strip()):
                drop = level
            continue
        if drop:
            continue
        line = re.sub(r"^[*#:;\s]+", "", line).strip()
        if line and not line.startswith("__"):
            out.extend(_split_sentences(re.sub(r"\s+", " ", line)))
    return out


# ---------------------------------------------------------------- retirement
_FMT_RX = {
    "test": re.compile(r"\btests?\b(?!\s*(?:captain|captaincy|leadership|vice))|\blongest format", re.I),
    "odi": re.compile(r"\bodis?\b(?!\s*(?:captain|captaincy|leadership|vice))|\bone[ -]day internationals?\b|"
                      r"\binternational one[ -]day\b|\b50[ -]over international", re.I),
    "t20i": re.compile(r"\bt20is?\b(?!\s*(?:captain|captaincy|leadership|vice))|\b(?:t20|twenty ?20) "
                       r"internationals?\b|\binternational (?:t20|twenty ?20)s?\b", re.I),
}
_LIMITED_RX = re.compile(r"(?:limited[ -]overs?|white[ -]ball)\s+international|"
                         r"international\s+(?:limited[ -]overs?|white[ -]ball)", re.I)
# Retirement from all cricket. "professional cricket" alone is left out: county players use it while
# still playing (amateur) international cricket for associate nations.
_ALL_RX = re.compile(r"(?:the\s+)?all\s+(?:(?:three|the)\s+)?(?:forms?|formats?|types?)(?:\s+of\s+(?:the\s+)?"
                     r"(?:professional\s+|competitive\s+)?(?:game|cricket|sport))?"
                     r"(?!\s+of\s+(?:domestic|first|franchise|county|t20\b|twenty|club))"
                     r"|(?:forms?|formats?|types?)\s+of\s+(?:the\s+)?(?:game|cricket|sport)\b"
                     r"|all\s+(?:professional\s+|competitive\s+|top[ -]level\s+)?cricket\b"
                     r"|(?:competitive\s+|top[ -]level\s+|active\s+)?cricket\b"
                     r"(?!\s+(?:administration|commentary|board|coaching|journalism))"
                     r"|(?:the\s+)?(?:game|sport)\b", re.I)
_MONTHS_ALT = "January|February|March|April|May|June|July|August|September|October|November|December"
_RESTRICTED_RX = re.compile(r"\s*(?:in|for)\s+(?!(?:%s)\b)[A-Z]" % _MONTHS_ALT)  # "... from cricket in South Africa"
_CONTINUES_RX = re.compile(r"continu\w*\s+to\s+(?:play|represent)\b[^.]{0,40}?(?:\bfor\s+[A-Z]|international|"
                           r"national)")
_REVERSED_DECISION_RX = re.compile(r"\b(?:revers|rescind|overturn|revok)\w*\s+(?:his|her|their|this|that|the)\s+"
                                   r"(?:earlier\s+|previous\s+)?decision\b", re.I)
_DOMESTIC_RX = re.compile(r"first[ -]class|list a|domestic|county|franchise|\bleagues?\b|\bipl\b|\bpsl\b|\bbbl\b|"
                          r"\bbpl\b|\bcpl\b|\blpl\b|\bwpl\b|\bwbbl\b|\bsa20\b|\bilt20\b|\bmlc\b|\bhundred\b|"
                          r"\bt10\b|premier league|big bash|super smash|sheffield shield|ranji|provincial|"
                          r"\bstate\b|legends|masters|club cricket", re.I)
_OBJ_CUT = re.compile(r",\s+(?!(?:and\s+)?(?:the\s+)?(?:tests?|odis?|t20is?|one[ -]day|twenty ?20|t20)\b)|"
                      r"\s+(?:in|on|at|after|following|before|during|with|to|while|but|because|due|so|when|"
                      r"citing|ahead|amid|having|as|later|through|via|for|until|since|by|"
                      r"and\s+(?!(?:from\s+)?(?:the\s+)?(?:all\s+)?(?:tests?|odis?|t20is?|one[ -]day|twenty ?20|"
                      r"t20|international|first|list|limited|white|domestic|county|franchise|club)\b))\b", re.I)
# A retirement from a role rather than from playing ("retired from the Test captaincy").
_ROLE_RX = re.compile(r"\b(?:captain\w*|vice[ -]captain\w*|leadership|umpir\w*|coach\w*|commentary|"
                      r"administrat\w*|selector\w*|refere\w*|management|board)\b", re.I)
# "the retirement from international cricket of fellow spinner Nicky Boje"
_OF_SUBJECT_RX = re.compile(r"\s+of\s+(?=(?:[a-z-]+\s+){0,3}[A-Z])")
_REPORT_RX = re.compile(r"\b(?:announc\w*|sa(?:id|ys)|stat\w*|declar\w*|confirm\w*|reveal\w*|indicat\w*|"
                        r"told|insist\w*)\s+(?:that\s+)?$", re.I)
_RETIRE_RX = re.compile(r"\b(?:retire[ds]?|retiring|retirement|quit(?:s|ting)?)\s+"
                        r"(?:(?:officially|formally|permanently|completely|fully|finally|also|effectively|"
                        r"immediately)\s+)?from\s+(?:playing\s+)?(?P<obj>[^.;:!?]{1,120})", re.I)
_RETIRE_POSS_RX = re.compile(r"\b(?:his|her|their)\s+(?P<obj>(?:test|odi|t20i|international|one[ -]day "
                             r"international|t20 international|twenty20 international)(?:\s+and\s+"
                             r"(?:test|odi|t20i))?)\s+retirement\b", re.I)
_CALLED_RX = re.compile(r"\bcalled\s+time\s+on\s+(?:his|her|their)\s+(?P<obj>[^.;:!?]{1,60}?)\s+career\b", re.I)
_UNRETIRE_RX = re.compile(
    r"\b(?:(?:came|come|comes|coming)\s+(?:back\s+)?out\s+of\s+(?:(?:his|her|their)\s+)?(?:[\w-]+\s+){0,3}?"
    r"retirement|revers(?:ed|es|ing)\s+(?:his|her|their|an?|the)\s+(?:(?:[\w-]+\s+){0,3}?retirement|"
    r"(?:(?:earlier|initial|previous|original)\s+)?decision\s+to\s+retire)|"
    r"(?:rescind|withdr[ae]w|withdrawn|withdrawing|overturn|revok)\w*\s+"
    r"(?!from\b)(?:(?:his|her|their|my|the)\s+)?(?:earlier\s+|previous\s+)?(?:(?:[\w-]+\s+){0,3}?retirement|decision\s+to\s+"
    r"retire)|u-?turn\s+on\s+"
    r"(?:his|her|their)\s+(?:[\w-]+\s+){0,3}?retirement|return(?:ed|s|ing)?\s+from\s+(?:(?:his|her|their)\s+)?"
    r"(?:international\s+)?retirement|un-?retire[ds]?|unretir(?:ed|ing|ement))", re.I)
_NEG_RX = re.compile(r"\b(?:not|never|no|rumou?rs?|speculat\w*|consider\w*|contemplat\w*|den(?:y|ied|ies)|"
                     r"rul(?:ed|ing|es)\s+out|refus\w*|hint\w*|postpon\w*|delay\w*|reconsider\w*|urg\w*|"
                     r"persuad\w*|convinc\w*|threat\w*|nearly|almost|likely|might|could|possib\w*|if|"
                     r"whether|plan(?:s|ned|ning)?\s+to|intend\w*|expected|set\s+to|reportedly|asked|"
                     r"pressure|calls?\s+for|temporar\w*|wish\w*|want\w*|desir\w*|hop(?:e|ed|es|ing)|keen|"
                     r"(?-i:may))\b|n't\b", re.I)
_DENIED_RX = re.compile(r"\b(?:den(?:y|ied|ies)|speculation|rumou?rs?|later\s+revers\w*|did\s+not)\b", re.I)
# A year, or a season/span whose end year is taken ("2010-11", "1999-2003").
_YEAR_RX = re.compile(r"\b(1[89]\d\d|20\d\d)(?:\s*[-/]\s*(\d{4}|\d{2})(?!\d))?\b")
_SPAN_START_RX = re.compile(r"^\s*(?:-|until|till|to|through)\b")


def _year_of(m: re.Match) -> int:
    y, end = m.group(1), m.group(2)
    if end:
        e = int(y[:2] + end) if len(end) == 2 else int(end)
        if int(y) < e <= int(y) + 30:
            return e
    return int(y)

_SELF = {"he", "she", "they", "i"}
_POSS = {"his", "her", "their", "my"}
_PARTICLES = {"de", "du", "van", "der", "den", "von", "ul", "al", "el", "bin", "bint", "da", "di", "le",
              "la", "ten", "ter", "and", "&"}
_RELATIVES = {"father", "mother", "brother", "sister", "son", "daughter", "uncle", "aunt", "cousin", "wife",
              "husband", "nephew", "niece", "grandfather", "teammate", "colleague", "partner", "coach",
              "mentor", "predecessor", "successor", "idol", "who", "whom", "which"}
_NOT_NAMES = set("""
the a an in on at after following during before when while however later then this that these those it as
with despite since also ahead prior upon shortly just having due by from for of to but and or although though
once until within over under through throughout eventually finally subsequently meanwhile thereafter
afterwards soon initially previously earlier two three four five six seven eight nine ten first second third
fourth last next former his her their he she they its there here what where why how both all each every
some many most few several another other no not yes on upon amid among between towards toward around about
following having being despite nevertheless nonetheless moreover furthermore additionally consequently thus
therefore accordingly instead likewise similarly overall today yesterday tomorrow ultimately notably
january february march april may june july august september october november december
monday tuesday wednesday thursday friday saturday sunday
test tests odi odis t20i t20is t20 twenty20 international internationals cricket world cup trophy series
championship league premier one day ashes final finals semi quarter match matches tour tournament season
board council club county ground stadium oval park award awards player captain team squad side games
olympics commonwealth gold silver bronze medal asia asian champions super smash shield
icc bcci pcb bcb ecb slc nzc csa ca zc wicb cwi acb mcc ipl psl bbl cpl bpl lpl sa20 ilt20 mlc wpl wbbl
rcb csk kkr srh pbks lsg mi gt rr dc odis
instagram twitter facebook youtube media press news statement conference interview
india indian australia australian england english south africa african new zealand pakistan pakistani
sri lanka lankan west indies indian bangladesh bangladeshi zimbabwe zimbabwean afghanistan afghan ireland
irish scotland scottish netherlands dutch united arab emirates nepal nepalese oman namibia namibian states
america american canada canadian kenya kenyan hong kong papua guinea wales welsh british
government prime minister president chairman chief selector selectors
""".split())


def _tokens(s: str) -> list[str]:
    toks = re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)*|\d+|&", s)
    return [re.sub(r"['’]s$", "", t) for t in toks]


def _name_like(t: str) -> bool:
    return len(t) > 1 and t[0].isupper() and t.lower() not in _NOT_NAMES and t.lower() not in _PARTICLES


def name_tokens(names: Iterable[str]) -> set[str]:
    out = set()
    for n in names:
        n = re.sub(r"\s*\([^)]*\)\s*$", "", n or "")
        out |= {t.lower() for t in _tokens(n) if len(t) > 1 and t.lower() not in _PARTICLES}
    return out


def _run_is_self(toks: list[str], i: int, step: int, names: set[str]) -> bool:
    """Collect the proper-name run through toks[i] and test each person in it."""
    run = []
    while 0 <= i < len(toks):
        t = toks[i]
        if _name_like(t) or t.lower() in _PARTICLES or (len(t) == 1 and t.isupper()):
            run.append(t); i += step
        else:
            break
    if step < 0:
        run.reverse()
    persons, cur = [], []
    for t in run + ["and"]:
        if t.lower() in ("and", "&"):
            if cur:
                persons.append(cur)
            cur = []
        elif _name_like(t):
            cur.append(t.lower())
    return any(p and all(t in names for t in p) for p in persons)


def _reporter(toks: list[str], i: int, names: set[str]) -> bool | None:
    """For a pronoun at toks[i] in reported speech ("Simpson ... announced that he"),
    whether the reporting subject is the player; None when it is not reported speech."""
    j = i - 1
    if j >= 0 and toks[j].lower() == "that":
        j -= 1
    if j < 0 or not _REPORT_RX.search(toks[j] + " "):
        return None
    group = toks[i].lower() == "they"  # "He along with Sangakkara announced that they would retire"
    seen = None
    for k in range(j - 1, max(j - 7, -1), -1):
        tl = toks[k].lower()
        if tl in _SELF:
            return True
        if tl in _RELATIVES:
            return False if not group else seen
        if _name_like(toks[k]):
            if _run_is_self(toks, k, -1, names):
                return True
            if not group:
                return False
            seen = False
    return seen


def _decide(toks: list[str], names: set[str], backward: bool) -> bool | None:
    rng = range(len(toks) - 1, -1, -1) if backward else range(len(toks))
    for i in rng:
        tl = toks[i].lower()
        if tl in _SELF:
            if backward:
                rep = _reporter(toks, i, names)
                if rep is not None:
                    return rep
            return True
        if tl in _RELATIVES:
            return False
        if _name_like(toks[i]):
            return _run_is_self(toks, i, -1 if backward else 1, names)
    return None


def _is_self(before: str, after: str, names: set[str], poss: bool = False) -> bool:
    toks = _tokens(before)
    d = _decide(toks, names, backward=True)
    if d is not None:
        return d
    if poss or any(t.lower() in _POSS for t in toks[-4:]):
        return True
    d = _decide(_tokens(after)[:15], names, backward=False)
    return bool(d)


def _formats(obj: str) -> set[str]:
    o = obj.strip()
    fm = {f for f, rx in _FMT_RX.items() if rx.search(o)}
    if _LIMITED_RX.search(o):
        fm |= {"odi", "t20i"}
    if fm:
        return fm
    if re.search(r"\binternational", o, re.I):
        return {"international"}
    if _DOMESTIC_RX.search(o[:40]):
        return set()
    return {"all"} if _ALL_RX.match(o) else set()


def _unretire_formats(window: str) -> set[str] | None:
    fm = {f for f, rx in _FMT_RX.items() if rx.search(window)}
    if _LIMITED_RX.search(window):
        fm |= {"odi", "t20i"}
    if fm:
        return fm
    if re.search(r"\binternational|national (?:team|side|selection)", window, re.I):
        return {"international"}
    if _DOMESTIC_RX.search(window):
        return None
    return {"international"}


def _clause_before(sent: str, pos: int) -> str:
    head = sent[:pos]
    cut = max(head.rfind(","), head.rfind(";"), head.rfind("("))
    return head[cut + 1:]


def _evidence(items: list[tuple[str, int]], limit: int = 200) -> str:
    seen: dict[str, int] = {}
    for sent, pos in items:
        seen.setdefault(sent, pos)
    items = list(seen.items())
    share = (limit - 3 * (len(items) - 1)) // max(len(items), 1)
    parts = []
    for sent, pos in items:
        if len(sent) > share:  # window around the match, on word boundaries
            start = max(0, min(pos - share // 3, len(sent) - share))
            if start:
                start = sent.find(" ", start) + 1 or start
            piece = sent[start:start + share]
            if start + share < len(sent) and " " in piece:
                piece = piece.rsplit(" ", 1)[0]
            sent = piece.strip()
        parts.append(sent)
    return " | ".join(parts)[:limit]


def retirement_events(sentences: list[str], names: set[str]) -> list[tuple]:
    """(year, order, kind 're'|'un', formats, sentence, match pos) in article order."""
    events, carry, last_re = [], None, -9
    for idx, sent in enumerate(sentences):
        found, masked = [], sent
        for m in _UNRETIRE_RX.finditer(sent):
            masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
            fm = _unretire_formats(sent[m.start():m.end() + 120])
            if fm is None or _NEG_RX.search(_clause_before(sent, m.start())):
                continue
            if _is_self(sent[:m.start()], sent[m.end():], names, poss=True):
                found.append((m.start(), m.end(), "un", fm))
        if not found and idx - last_re <= 2:  # "She reversed her decision" right after a retirement
            m = _REVERSED_DECISION_RX.search(sent)
            if m and _is_self(sent[:m.start()], sent[m.end():], names, poss=True):
                found.append((m.start(), m.end(), "un", {"international"}))
        for rx, poss in ((_RETIRE_RX, False), (_RETIRE_POSS_RX, True), (_CALLED_RX, False)):
            for m in rx.finditer(masked):
                obj = m.group("obj")
                cut = _OBJ_CUT.search(obj)
                if cut:
                    obj = obj[:cut.start()]
                subject = None
                of = _OF_SUBJECT_RX.search(obj)
                if of and rx is _RETIRE_RX:  # "retirement from X of <someone>"
                    subject = _decide(_tokens(obj[of.end():]), names, backward=False)
                    obj = obj[:of.start()]
                role = _ROLE_RX.search(obj)
                if role:  # "retired from the captaincy and from Test cricket" keeps only the playing part
                    rest = re.match(r"\s*(?:,\s*)?and\s+(?:from\s+)?(.*)", obj[role.end():])
                    if not rest:
                        continue
                    obj = rest.group(1)
                fm = _formats(obj)
                if not fm or _NEG_RX.search(_clause_before(sent, m.start()) + " " + sent[m.start():m.start("obj")]):
                    continue
                end = m.start("obj") + (cut.start() if cut else len(m.group("obj"))) if rx is _RETIRE_RX else m.end()
                if _DENIED_RX.search(sent[end:end + 80]):
                    continue
                if "all" in fm:  # all cricket, unless restricted to one country or still playing internationally
                    if _RESTRICTED_RX.match(sent[end:]) or _CONTINUES_RX.search(sent[end:]):
                        continue
                    fm = {"international"}
                if subject is False:
                    continue
                if subject or _is_self(sent[:m.start()], sent[end:], names, poss=poss):
                    found.append((m.start(), end, "re", fm))
                    last_re = idx
        found.sort(key=lambda f: f[0])
        year = carry
        for k, (pos, end, kind, fm) in enumerate(found):
            nxt = found[k + 1][0] if k + 1 < len(found) else len(sent)
            after = _YEAR_RX.search(sent, end, nxt) if end < nxt else None
            # a lead-in year that opens a span ("from 2021 until his retirement") is not the event date
            before = [y for y in _YEAR_RX.finditer(sent, 0, pos)
                      if not _SPAN_START_RX.match(sent[y.end():])][-1:] if k == 0 else []
            # nearest year: a lead-in date ("On 8 May 2024, ...") or one following the matched phrase
            if before and (not after or pos - before[0].end() <= after.start() - end):
                year = _year_of(before[0])
            elif after:
                year = _year_of(after)
            events.append((year, len(events), kind, fm, sent, pos))
        ys = list(_YEAR_RX.finditer(sent))
        if ys:
            carry = _year_of(ys[-1])
    return events


def detect_retirement(text: str | None, names: Iterable[str],
                      last_years: dict[str, str] | None = None) -> dict[str, str]:
    """Retirement flags from explicit statements in the article body.

    A come-back that names formats clears those formats; one that names none
    undoes the international retirement in effect (restoring earlier
    format-level retirements). With last_years ({'test': '2025', ...} from the
    infobox), a flag is dropped when the player appeared in that format after
    the year of the retirement statement."""
    keys = ("test", "odi", "t20i", "international")
    state: dict[str, tuple | None] = dict.fromkeys(keys)  # (sentence, pos, latest year asserting it)
    before_intl: dict | None = None
    events = retirement_events(article_sentences(text), name_tokens(names))
    for y, order, kind, fm, sent, pos in sorted(events, key=lambda e: (e[0] or 0, e[1])):
        if kind == "re":
            if "international" in fm and not state["international"]:
                before_intl = dict(state)
            for f in (keys if "international" in fm else fm):
                old = state[f]  # evidence is the latest statement; its year never moves backwards
                state[f] = (sent, pos, y or (old[2] if old else None))
        elif fm == {"international"}:
            if state["international"]:
                state = dict(before_intl or dict.fromkeys(keys))
        else:
            for f in fm | {"international"}:
                state[f] = None
    last = {k: int(v) for k, v in (last_years or {}).items() if str(v).isdigit()}
    # a later appearance undoes an international retirement like an unreported come-back
    if state["international"] and state["international"][2] and \
            any(v > state["international"][2] for v in last.values()):
        state = dict(before_intl or dict.fromkeys(keys))
    for f in ("test", "odi", "t20i"):
        if state[f] and state[f][2] and last.get(f, 0) > state[f][2]:
            state[f] = None
    out = {f"retired_{k}": "1" if state[k] else "" for k in keys}
    out["retirement_evidence"] = _evidence([state[k][:2] for k in keys if state[k]])
    return out


# ------------------------------------------------------------------- parse
def lead_names(text: str | None) -> list[str]:
    """Bold names in the lead paragraph (full names and aliases such as 'Riyad')."""
    lead = re.split(r"\n==", _without_refs(text or ""), maxsplit=1)[0]
    for _ in range(6):  # innermost templates first, so the infobox goes too
        lead, n = re.subn(r"\{\{[^{}]*\}\}", "", lead)
        if not n:
            break
    out = [strip_markup(n) for n in re.findall(r"'''(.+?)'''", lead)[:4]]
    return [n for n in out if n and len(n) <= 80]


def parse_player(text: str | None, title: str = "") -> dict[str, str]:
    """All article-derived columns for one player page."""
    ib = cricketer_infobox(text)
    female = _truthy(ib.get("female"))
    row = {"full_name": _plain(ib.get("full_name") or ib.get("fullname")),
           "birth_date": parse_date(ib.get("birth_date")),
           "country": "; ".join(c for c in (country_name(ib.get(k)) for k in ("country", "country2", "country3")) if c),
           "bowling_style_raw": _plain(ib.get("bowling")), "role_raw": _plain(ib.get("role"))}
    row["batting_hand"] = batting_hand(_plain(ib.get("batting")))
    row["bowling_class"], row["bowling_family"], row["bowling_arm"] = bowling(row["bowling_style_raw"])
    row["role"] = role(row["role_raw"])
    spans = _spans(ib)
    row["international_span"] = "; ".join(spans)
    row["active_international"] = active_international(spans)
    for fmt, col in (("test", "test"), ("odi", "odi"), ("t20i", "t20i")):
        row[f"last_{col}_year"] = _last_year(ib, fmt)
        row[f"{col}_cap"] = _caps(ib, fmt)
    row["stats_as_of"] = _plain(f"{ib.get('date', '')} {ib.get('year', '')}")
    stats = career(ib, female)
    row["career_json"] = json.dumps(stats, ensure_ascii=False) if stats else ""
    row.update(detect_retirement(text, [title, row["full_name"], _plain(ib.get("name"))] + lead_names(text),
                                 {f: row[f"last_{f}_year"] for f in ("test", "odi", "t20i")}))
    row["death_date"] = parse_date(ib.get("death_date"), "death")
    row["gender"] = gender(ib, text or "")
    row["has_infobox"] = "1" if ib else "0"
    return row


# --------------------------------------------------------------------- run
def candidates(resolver: Resolver, warehouse: str | Path = "data/warehouse") -> pd.DataFrame:
    """Cricsheet players (with appearances) whose cricinfo id has an enwiki article."""
    wh = Path(warehouse)
    players = pd.read_parquet(wh / "players.parquet", columns=["player", "id"])
    played = pd.read_parquet(wh / "appearances.parquet", columns=["player"])["player"].unique()
    ids = set(players.loc[players["player"].isin(played), "id"])
    wd = resolver.wd.dropna(subset=["title"]).drop_duplicates("cricinfo")
    page = {int(c): (q, t) for q, c, t in zip(wd["qid"], wd["cricinfo"], wd["title"])}
    rows = [(ident, ci, *page[ci]) for ci, ident in resolver.by_cricinfo.items() if ident in ids and ci in page]
    df = pd.DataFrame(rows, columns=["cricsheet_id", "cricinfo", "qid", "title"])
    return df.drop_duplicates("cricsheet_id").reset_index(drop=True)


def reference_titles(out_dir: str | Path) -> list[str]:
    titles: list[str] = []
    for name in REFERENCE_LISTS:
        p = Path(out_dir) / name
        if p.exists():
            df = pd.read_csv(p, dtype=str)
            if "wikipedia_title" in df:
                titles += [t.strip() for t in df["wikipedia_title"].dropna() if t.strip()]
    return list(dict.fromkeys(titles))


def fetch(wiki: Wiki, titles: list[str]) -> dict[str, dict]:
    pages = wiki.wikitext(titles)
    retry = [t for t, v in pages.items() if v["text"] is None]
    for i in range(0, len(retry), 10):  # oversized batches come back without content
        pages.update(wiki.wikitext(retry[i:i + 10]))
    return pages


def _is_disambiguation(text: str) -> bool:
    return bool(re.search(r"\{\{\s*(?:disambiguation|disambig|dab|hndis|human name disambiguation|"
                          r"set index)", text, re.I))


def _not_biography(page: dict) -> bool:
    """Disambiguation pages and lists that a player title redirects to."""
    return _is_disambiguation(page["text"]) or page["title"].lower().startswith("list of ")


# --------------------------------------------------------------- identity
_PROFILE_RX = re.compile(r"espncricinfo\.com/(?:cricketers/[a-z0-9-]*?-|(?:[a-z]+/)*content/player/|player/)"
                         r"(\d{3,8})\b", re.I)


_NAME_FORMS = {"mohd": "mohammad", "md": "mohammad", "muhammad": "mohammad", "mohammed": "mohammad",
               "mohamed": "mohammad", "muhammed": "mohammad"}
_HONORIFICS = {"nawab", "yuvraj", "maharaja", "maharajkumar", "raja", "prince", "sir", "lord"}


def _fold_tokens(name: str | None) -> list[str]:
    s = re.sub(r"\s*\([^)]*\)\s*$", "", name or "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return [_NAME_FORMS.get(t, t) for t in re.findall(r"[a-z]+", re.sub(r"['’`]", "", s))]


def _similar(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 4 and SequenceMatcher(None, a, b).ratio() >= 0.75)


def same_person(article_names: Iterable[str], register_names: Iterable[str]) -> bool:
    """Loose check that a register name ('LJ Woodcock', 'Ahmed Shehzad') can name the
    article's subject, allowing transliteration variants, initials in any order
    ('HHC Gunaratne' for Chandima Gunaratne) and changed surnames when the initials
    of the article's full name match ('LK Newton' for Laura Kelly MacLeod)."""
    arts = [t for t in (_fold_tokens(n) for n in article_names) if t]
    if not arts:
        return True
    tokens = {t for a in arts for t in a}
    joined = {"".join(a) for a in arts}
    for reg in register_names:
        raw = (reg or "").split()
        rt = _fold_tokens(reg)
        if not rt:
            continue
        initials = raw[0].lower() if len(raw) > 1 and raw[0].isalpha() and raw[0].isupper() and len(raw[0]) <= 7 else ""
        words = rt[1:] if initials else rt
        matched = [w for w in words if any(_similar(w, t) for t in tokens)
                   or (len(w) > 3 and any(w in j for j in joined))]
        # first letters of the article's other names ("Hiri Hiri" keeps one "hiri")
        others = {t[0] for a in arts for t in (a[:-1] if matched and _similar(matched[-1], a[-1]) else
                                               [t for t in a if not any(_similar(w, t) for w in matched)])}
        if len(matched) >= 2 or (len(matched) == len(words) == 1 and (not initials or set(initials) & others)):
            return True
        if matched and initials and set(initials) & others:
            return True
        if words[0] in _HONORIFICS and words[-1] in tokens:  # "Nawab of Pataudi"
            return True
        if len(words) > 1 and any(SequenceMatcher(None, "".join(words), j).ratio() >= 0.75 for j in joined):
            return True
        if len(initials) > 1 and any(initials in ("".join(t[0] for t in a[:-1]), "".join(t[0] for t in a))
                                     for a in arts if len(a) > 1):
            return True
    return False


def profile_cricsheet_id(text: str | None, names: list[str], by_cricinfo: dict[int, str],
                         register_names: dict[str, list[str]]) -> tuple[int, str] | None:
    """(cricinfo id, Cricsheet id) from the article's own ESPNcricinfo profile links when
    neither Wikidata nor a {{Cricinfo}} template gives one. Profiles of relatives or
    team-mates are rejected by the name check; more than one survivor is ambiguous."""
    hits = {}
    for ci in dict.fromkeys(int(i) for i in _PROFILE_RX.findall(text or "")):
        ident = by_cricinfo.get(ci)
        if ident and same_person(names, register_names.get(ident, [])):
            hits.setdefault(ident, ci)
    if len(hits) == 1:
        ident, ci = next(iter(hits.items()))
        return ci, ident
    return None


def _article_names(title: str, text: str | None, info: dict) -> list[str]:
    return [title, info.get("full_name", ""), _plain(cricketer_infobox(text).get("name"))] + lead_names(text)


def register_names(people_csv: str | Path, warehouse: str | Path) -> dict[str, list[str]]:
    """Cricsheet id -> names it is known by (register name, unique name, warehouse name)."""
    people = pd.read_csv(people_csv, dtype=str, usecols=lambda c: c in ("identifier", "name", "unique_name"))
    out: dict[str, list[str]] = {}
    for col in ("name", "unique_name"):
        if col in people:
            for ident, n in zip(people["identifier"], people[col]):
                if isinstance(n, str):
                    out.setdefault(ident, []).append(n)
    p = Path(warehouse) / "players.parquet"
    if p.exists():
        wh = pd.read_parquet(p, columns=["id", "name"])
        for ident, n in zip(wh["id"], wh["name"]):
            if isinstance(n, str):
                out.setdefault(ident, []).append(n)
    return out


def run(wiki: Wiki, resolver: Resolver, out_dir: str | Path = "data/reference",
        extra_titles: Iterable[str] | None = None, *, warehouse: str | Path = "data/warehouse",
        people_csv: str | Path = "data/raw/people.csv") -> dict:
    out_dir = Path(out_dir)
    cands = candidates(resolver, warehouse)
    extra = list(dict.fromkeys(list(extra_titles or []) + reference_titles(out_dir)))
    titles = list(dict.fromkeys(list(cands["title"]) + extra))
    pages = resolver.resolve_pages(fetch(wiki, titles))
    missing = sorted(t for t in titles if pages[t]["text"] is None)
    reg_names = register_names(people_csv, warehouse)
    parsed: dict[str, dict] = {}

    def parsed_for(page: dict) -> dict:
        if page["title"] not in parsed:
            parsed[page["title"]] = parse_player(page["text"], page["title"])
        return parsed[page["title"]]

    rows, mismatch, covered, not_bio = [], [], set(), []
    for c in cands.itertuples(index=False):
        page = pages[c.title]
        if page["text"] is None:
            continue
        if page["qid"] and page["qid"] != c.qid:
            mismatch.append(c.title)
            continue
        if _not_biography(page):
            not_bio.append(c.title)
            continue
        covered.add(page["title"])
        rows.append({"wikipedia_title": page["title"], "revid": page["revid"], "qid": c.qid,
                     "cricinfo_id": c.cricinfo, "cricsheet_id": c.cricsheet_id, **parsed_for(page)})
    skipped_extra, from_profile = [], []
    for t in extra:
        page = pages[t]
        if page["text"] is None or page["title"] in covered:
            continue
        info = parsed_for(page)
        if _not_biography(page) or (info["has_infobox"] == "0" and not page["cricinfo"]):
            skipped_extra.append(t)
            continue
        cricinfo, cricsheet = page["cricinfo"], page["cricsheet_id"]
        if not cricinfo:  # no Wikidata id and no {{Cricinfo}}: try the article's own profile links
            hit = profile_cricsheet_id(page["text"], _article_names(page["title"], page["text"], info),
                                       resolver.by_cricinfo, reg_names)
            if hit:
                cricinfo, cricsheet = hit
                from_profile.append(page["title"])
        covered.add(page["title"])
        rows.append({"wikipedia_title": page["title"], "revid": page["revid"], "qid": page["qid"] or "",
                     "cricinfo_id": cricinfo or "", "cricsheet_id": cricsheet or "", **info})

    # identity guards: the register name must fit the article, and one Cricsheet id names one article
    texts = {v["title"]: v["text"] for v in pages.values() if v["text"] is not None}
    name_rejected, shared = [], []
    for r in rows:
        title = r["wikipedia_title"]
        if r["cricsheet_id"] and not same_person(_article_names(title, texts[title], r),
                                                 reg_names.get(r["cricsheet_id"], [])):
            name_rejected.append(r["wikipedia_title"])
            r["cricsheet_id"] = ""
    counts = pd.Series([r["cricsheet_id"] for r in rows if r["cricsheet_id"]], dtype=str).value_counts()
    for r in rows:
        if r["cricsheet_id"] and counts.get(r["cricsheet_id"], 0) > 1:
            shared.append(r["wikipedia_title"])
            r["cricsheet_id"] = ""

    df = pd.DataFrame(rows, columns=COLUMNS + EXTRA_COLUMNS).fillna("")
    for col in ("revid", "cricinfo_id"):
        df[col] = df[col].map(lambda v: str(int(v)) if str(v).strip() not in ("", "None", "nan") else "")
    df = df.sort_values(["wikipedia_title", "cricsheet_id"], kind="stable")
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "players_wiki.csv", index=False, encoding="utf-8")

    filled = lambda c: int((df[c] != "").sum())
    return {"candidates": len(cands), "extra_titles": len(extra), "titles_requested": len(titles),
            "fetched": len(titles) - len(missing), "missing": missing, "qid_mismatch": mismatch,
            "not_biography": not_bio, "extra_skipped": skipped_extra, "ids_from_profile_links": from_profile,
            "ids_dropped_name_mismatch": name_rejected, "ids_dropped_shared": shared,
            "rows": len(df), "articles": df["wikipedia_title"].nunique(),
            "infobox_found": int((df["has_infobox"] == "1").sum()), "birth_date_filled": filled("birth_date"),
            "hand_filled": filled("batting_hand"), "bowling_class_filled": filled("bowling_class"),
            "bowling_family_filled": filled("bowling_family"), "role_filled": filled("role"),
            "span_filled": filled("international_span"), "career_filled": filled("career_json"),
            "active_international": df["active_international"].value_counts().to_dict(),
            "retired_international": filled("retired_international"), "retired_test": filled("retired_test"),
            "retired_odi": filled("retired_odi"), "retired_t20i": filled("retired_t20i"),
            "cricsheet_id_rows": filled("cricsheet_id"),
            "cricsheet_match_rate": round(filled("cricsheet_id") / len(df), 4) if len(df) else 0.0}


if __name__ == "__main__":
    w = Wiki("data/cache/wiki", min_interval=0.5)
    stats = run(w, Resolver("data/raw/people.csv", w))
    print(json.dumps({k: (v if not isinstance(v, list) else v[:50]) for k, v in stats.items()}, indent=1))
