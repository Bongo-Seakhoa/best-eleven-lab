"""Network-free tests for the Wikipedia career-list parser.

Fixtures under tests/fixtures/enrich/careers_*.html are trimmed copies of real
list pages (a few rows each), except careers_synthetic_rows.html, which is
invented and labelled as such.
"""
from pathlib import Path

import pandas as pd
import pytest

from best_eleven.enrich import careers as C
from best_eleven.enrich.wiki import html_tables

FIX = Path(__file__).parent / "fixtures" / "enrich"


def parse(name, fmt="Test", gender="male"):
    html = (FIX / name).read_text(encoding="utf-8")
    rows, stats = C.parse_page(html, country="X", gender=gender, fmt=fmt, source_page="Page",
                               revid=123)
    return {r["name"]: r for r in rows}, stats


def test_multilevel_header_split_tables_and_markers():
    rows, st = parse("careers_sa_test.html")
    assert st["tables"] == 2  # pre- and post-readmission tables
    assert st["legend"] == {"‡": "captain", "†": "keeper"}
    assert list(rows) == ["Owen Dunell", "Charlie Finlason", "Percy Sherwell", "Hansie Cronje",
                          "Jacques Kallis"]
    k = rows["Jacques Kallis"]
    assert (k["cap"], k["matches"], k["runs"], k["high_score"], k["bat_avg"]) == ("262", "165", "13206", "224", "55.25")
    assert (k["balls_bowled"], k["runs_conceded"], k["wickets"], k["best_bowling"]) == ("20172", "9535", "291", "6/54")
    assert (k["first_year"], k["last_year"], k["wikipedia_title"]) == ("1995", "2013", "Jacques Kallis")
    assert "bowl_avg 32.63 differs" in k["parse_note"]  # page's own inconsistency is kept and noted
    assert rows["Hansie Cronje"]["cap"] == "237"  # overall cap, not the post-1992 cap column
    assert rows["Owen Dunell"]["high_score"] == "26*"
    assert rows["Owen Dunell"]["captain_marker"] == "1"
    s = rows["Percy Sherwell"]
    assert (s["captain_marker"], s["keeper_marker"], s["stumpings"]) == ("1", "1", "16")
    assert rows["Charlie Finlason"]["captain_marker"] == rows["Charlie Finlason"]["keeper_marker"] == ""
    assert rows["Charlie Finlason"]["revid"] == "123"


def test_inverted_group_row_header():
    df, _ = html_tables((FIX / "careers_eng_test.html").read_text(encoding="utf-8"))[0]
    assert C.map_columns(df.columns) == ["cap", "name", "first", "last", "matches", "runs", "high_score",
                                         "bat_avg", "balls_bowled", "wickets", "best_bowling", "bowl_avg",
                                         "catches", "stumpings", None]
    rows, _ = parse("careers_eng_test.html")
    e = rows["Tom Emmett"]
    assert (e["runs"], e["wickets"], e["best_bowling"], e["bowl_avg"], e["catches"]) == ("160", "9", "7/68", "31.55", "9")


def test_career_span_combined_hundreds_and_numeric_cast():
    rows, _ = parse("careers_aus_odi.html", fmt="ODI")
    c = rows["Ian Chappell"]
    assert (c["first_year"], c["last_year"], c["career_open"]) == ("1971", "1980", "")
    assert (c["hundreds"], c["fifties"], c["high_score"]) == ("0", "8", "86")
    assert (c["runs_conceded"], c["bowl_avg"], c["best_bowling"]) == ("23", "11.5", "2/14")
    p = rows["Oliver Peake"]  # capped, stats not yet on the page
    assert (p["cap"], p["first_year"], p["last_year"], p["career_open"], p["matches"]) == ("252", "2026", "", "1", "")


def test_short_row_values_after_defect_are_blanked():
    rows, st = parse("careers_ind_test.html")
    m = rows["Nayan Mongia"]
    assert (m["runs"], m["hundreds"], m["fifties"]) == ("1442", "1", "6")
    assert m["wickets"] == m["bowl_avg"] == m["catches"] == m["stumpings"] == ""
    assert "blanked as shifted" in m["parse_note"]
    d = rows["Debashish Mohanty"]  # full-length row: only the broken cell is dropped
    assert (d["bat_avg"], d["wickets"], d["best_bowling"]) == ("", "4", "4/78")
    assert rows["Amar Singh"]["wikipedia_title"] == "Amar Singh (cricketer)"
    assert st["unparsed"] == {"wickets": 1, "bowl_avg": 1, "bat_avg": 1}


def test_numeric_name_footnote_and_dash_bowling_figures():
    rows, _ = parse("careers_sa_odi.html", fmt="ODI")
    assert "Kepler Wessels" in rows and rows["Kepler Wessels"]["parse_note"] == "name footnote 1"
    assert rows["Allan Donald"]["best_bowling"] == "6/23"


def test_three_level_header_and_assumed_legend():
    rows, st = parse("careers_sa_women_t20i.html", fmt="T20I", gender="female")
    assert st["legend"] == {} and st["legend_assumed"] == ["‡", "†"]
    assert rows["Trisha Chetty"]["keeper_marker"] == "1" and rows["Trisha Chetty"]["stumpings"] == "28"
    assert rows["Cri-Zelda Brits"]["captain_marker"] == "1"
    assert (rows["Susan Benade"]["high_score"], rows["Susan Benade"]["fifties"]) == ("53*", "1")


def test_synthetic_junk_rows_custom_legend_and_misaligned_links():
    rows, st = parse("careers_synthetic_rows.html", fmt="ODI")
    assert list(rows) == ["Alpha Example", "Beta Sample"]
    assert st["skipped_rows"] == 3  # repeated header, footnote, total
    assert st["legend"] == {"§": "keeper", "¶": "captain"}
    a, b = rows["Alpha Example"], rows["Beta Sample"]
    assert (a["first_year"], a["last_year"], a["runs"], a["fifties"], a["hundreds"]) == ("1980", "1984", "1200", "2", "3")
    assert (a["runs_conceded"], a["bowl_avg"], a["economy"], a["best_bowling"]) == ("40", "40", "4", "1/20")
    assert (a["captain_marker"], b["keeper_marker"], b["career_open"]) == ("1", "1", "1")
    assert b["wikipedia_title"] == "Beta Sample (cricketer)"  # matched by name despite row offset


@pytest.mark.parametrize("first,last,span,expected", [
    (None, None, "1877–1890", ("1877", "1890", "")),
    (None, None, "1877–90", ("1877", "1890", "")),
    (None, None, "2025–", ("2025", "", "1")),
    (None, None, "2026–present", ("2026", "", "1")),
    (None, None, "2000", ("2000", "2000", "")),
    (1932, 1936.0, None, ("1932", "1936", "")),
    ("v England at Lord's, 1990", "2001[3]", None, ("1990", "2001", "")),
])
def test_years(first, last, span, expected):
    assert C.years(first, last, span) == expected


def test_numbers_and_names():
    assert C.to_number("13,289", True) == "13289"
    assert C.to_number(16.0, True) == "16"
    assert C.to_number(18.5, False) == "18.5"
    assert C.to_number("–", True) == C.to_number("5098+", True) == C.to_number("23l4", True) == ""
    assert C.to_number("10.00}", False) == "10"
    assert C.split_name("Mohammad Yousuf1, 2") == ("Mohammad Yousuf", set(), "1,2")
    assert C.split_name("Mitchell Hay †[a]") == ("Mitchell Hay", {"†"}, "")


def test_title_patterns():
    assert "List of United States women Twenty20 International cricketers" in C.candidate_titles(
        "United States of America", "female", "T20I")
    pat = C.title_regex("England", "male", "Test")
    assert pat.match("List of England Test cricketers (1877–1914)")
    assert not pat.match("List of England women Test cricketers")
    assert not pat.match("List of England Test cricket records")
    assert C.title_regex("India", "female", "ODI").match("List of India women One Day International cricketers")


class FakeWiki:
    """Answers existence queries from a fixed title set; no network."""

    def __init__(self, pages, redirects=None):
        self.pages, self.redirects = set(pages), redirects or {}

    def api(self, **p):
        if p.get("list") == "search":
            return {"query": {"search": []}}
        titles = p["titles"].split("|")
        reds = [{"from": t, "to": self.redirects[t]} for t in titles if t in self.redirects]
        out = [{"title": self.redirects.get(t, t)} | ({} if self.redirects.get(t, t) in self.pages else {"missing": True})
               for t in titles]
        return {"query": {"redirects": reds, "pages": out}}

    def parse(self, title, section=None):
        raise KeyError(title)


def test_discover_follows_redirects_and_reports_missing():
    pages = ["List of Australia Test cricketers", "List of Zimbabwe women ODI cricketers"]
    w = FakeWiki(pages, {"List of Zimbabwe women One Day International cricketers": "List of Zimbabwe women ODI cricketers"})
    found, missing = C.discover(w)
    assert found[("Australia", "male", "Test")] == ["List of Australia Test cricketers"]
    assert found[("Zimbabwe", "female", "ODI")] == ["List of Zimbabwe women ODI cricketers"]
    assert ("Australia", "female", "Test") in missing
    assert ("Scotland", "male", "Test") not in missing  # associate Tests are out of scope


def test_cap_checks():
    df = pd.DataFrame({"country": ["A"] * 4, "gender": ["male"] * 4, "format": ["ODI"] * 4,
                       "cap": ["1", "2", "2", "5"]})
    r = C.cap_checks(df).iloc[0]
    assert r["duplicate_caps"] == [2] and r["missing_caps"] == [3, 4]


def test_appearance_check_classes(tmp_path):
    pd.DataFrame({"player": [0, 1, 2], "id": ["aaaaaaaa", "bbbbbbbb", "cccccccc"]}).to_parquet(tmp_path / "players.parquet")
    pd.DataFrame({"match_id": [1, 2], "format": ["ODI", "T20I"], "gender": ["male", "male"],
                  "team_type": ["international", "international"], "year": [2010, 2010]}).to_parquet(tmp_path / "matches.parquet")
    pd.DataFrame({"match_id": [1, 2, 2], "team": ["Kenya", "Kenya", "Canada"],
                  "player": [0, 1, 2]}).to_parquet(tmp_path / "appearances.parquet")
    df = pd.DataFrame({"country": ["Kenya"] * 5, "gender": ["male"] * 5, "format": ["ODI"] * 5,
                       "name": list("ABCDE"), "wikipedia_title": list("ABCDE"),
                       "cricsheet_id": ["aaaaaaaa", "bbbbbbbb", "cccccccc", "dddddddd", "aaaaaaaa"],
                       "last_year": ["2012", "2012", "2012", "", "1999"]})
    r = C.appearance_check(df, tmp_path)
    assert r["checked"] == 4  # the 1999 career predates warehouse coverage
    assert (r["same_format"], r["other_format"], r["other_team_only"], r["no_international"]) == (1, 1, 1, 1)
