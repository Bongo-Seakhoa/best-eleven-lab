from pathlib import Path

import pandas as pd
import pytest
from lxml import html as lh

from best_eleven.enrich import captains as C

FIX = Path(__file__).parent / "fixtures" / "enrich"


def tables(name):
    return C.page_tables((FIX / name).read_text(encoding="utf-8"))


def frame(t, **base):
    rows, _ = C.parse_table(t)
    df = pd.DataFrame(rows)
    defaults = {"level": "international", "country_or_team": "X", "competition": "",
                "gender": "male", "format": "Test", "source_page": "p", "revid": 1}
    for k, v in {**defaults, **base}.items():
        df[k] = v
    df["wikipedia_title"] = df["link"].fillna("")
    df["cricsheet_id"] = ""
    for c in ("season_or_period", "notes"):
        df[c] = df[c].fillna("")
    return df


def by_name(rows, name):
    return [r for r in rows if r["name"] == name]


def test_grid_expands_rowspan_and_colspan():
    # synthetic table, invented values
    t = lh.fromstring("<table><tr><th>A</th><th>B</th><th>C</th></tr>"
                      "<tr><td rowspan='2'>x</td><td>1</td><td>2</td></tr>"
                      "<tr><td colspan='2'>Total</td></tr></table>")
    g = [[c["text"] for c in r] for r in C.grid(t)]
    assert g == [["A", "B", "C"], ["x", "1", "2"], ["x", "Total", "Total"]]


def test_per_series_test_table_with_total_rows():
    test, youth = tables("captains_test_series.html")
    assert C.classify(test, "international") == ("male", "Test")
    rows, totals = C.parse_table(test)
    assert [r["name"] for r in rows] == ["Owen Dunell", "William Milton", "William Milton",
                                         "Ernest Halliwell", "Ernest Halliwell", "Alfred Richards"]
    milton = by_name(rows, "William Milton")
    assert {r["link"] for r in milton} == {"William Henry Milton"}
    assert [r["season_or_period"] for r in milton] == ["1888-89", "1891-92"]
    assert milton[0]["opposition"] == "England" and milton[0]["location"] == "South Africa"
    assert milton[0]["number"] == "2"
    assert (milton[0]["played"], milton[0]["lost"], milton[0]["tied"]) == (1, 1, None)
    # explicit Total rows belong to their captain and agree with the series rows
    assert [(t["name"], t["played"], t["team_total"], t["diff"]) for t in totals] == [
        ("William Milton", 2, False, {}), ("Ernest Halliwell", 3, False, {})]
    assert by_name(rows, "Alfred Richards")[0]["notes"] == "deputised"
    assert by_name(rows, "Owen Dunell")[0]["notes"] == ""


def test_youth_and_tournament_tables_are_skipped():
    _, youth = tables("captains_test_series.html")
    assert C.classify(youth, "international") is None
    icc = {"headings": ["Men's cricket", "Captains in Men's ICC tournaments", ""], "caption": ""}
    assert C.classify(icc, "international") is None


def test_total_row_without_name_and_grand_total():
    (t,) = tables("captains_test_tail.html")
    rows, totals = C.parse_table(t)
    assert len(rows) == 4
    captain, team = totals
    assert (captain["name"], captain["team_total"], captain["played"], captain["diff"]) == (
        "Dhananjaya de Silva", False, 8, {})
    assert team["team_total"] and team["name"] == ""
    assert team["diff"]["played"] == (321, 8)  # fixture holds only one captain


def test_short_total_row_is_right_aligned():
    (t,) = tables("captains_test_short_total.html")
    rows, totals = C.parse_table(t)
    assert len(rows) == 11 and {r["name"] for r in rows} == {"Babar Azam"}
    (tot,) = totals
    assert (tot["name"], tot["played"], tot["won"], tot["lost"], tot["drawn"], tot["diff"]) == (
        "Babar Azam", 24, 11, 9, 4, {})


def test_single_row_odi_table():
    odi, _ = tables("captains_odi.html")
    assert C.classify(odi, "international") == ("female", "ODI")
    rows, totals = C.parse_table(odi)
    assert len(rows) == 17
    taylor = by_name(rows, "Stafanie Taylor")[0]
    # header order is Won, Tied, Lost: values are mapped by header name
    assert (taylor["played"], taylor["won"], taylor["tied"], taylor["lost"], taylor["no_result"],
            taylor["drawn"]) == (61, 24, 1, 33, 3, None)
    assert taylor["season_or_period"] == "2013-2022" and taylor["opposition"] == ""
    (grand,) = totals
    assert grand["team_total"] and grand["played"] == 249 and grand["diff"] == {}


def test_footnote_superscripts_are_dropped():
    _, t20 = tables("captains_odi.html")
    assert C.classify(t20, "international") == ("female", "T20I")
    rows, _ = C.parse_table(t20)
    m = by_name(rows, "Merissa Aguilleira")[0]
    assert (m["tied"], m["season_or_period"]) == (3, "2009-2015, 2019")
    assert by_name(rows, "Chinelle Henry")[0]["season_or_period"] == "2026-present"


def test_franchise_table():
    (t,) = tables("captains_franchise.html")
    assert C.classify(t, "franchise", "male") == ("male", "T20")
    rows, totals = C.parse_table(t)
    assert totals == []
    dhoni = by_name(rows, "MS Dhoni")[0]
    assert dhoni["teams"] == "Chennai Super Kings; Rising Pune Supergiant"
    assert dhoni["season_or_period"] == "2008-2025"
    assert (dhoni["played"], dhoni["won"], dhoni["lost"], dhoni["tied"], dhoni["no_result"]) == (
        235, 136, 97, 0, 2)


@pytest.mark.parametrize("text, expected", [
    ("1888-89", [1888, 1889]), ("1934/5", [1934, 1935]), ("1999/00", [1999, 2000]),
    ("2003-2011", [2003, 2011]), ("2021-present", [2021]), ("2025 (WTC Final)", [2025]),
    ("2009-2015, 2019", [2009, 2015, 2019]), ("", [])])
def test_years(text, expected):
    assert C.years(text) == expected


def test_aggregate_sums_rows_and_checks_page_totals():
    test, _ = tables("captains_test_series.html")
    agg = C.aggregate(frame(test))
    milton = agg[agg["name"] == "William Milton"].iloc[0]
    assert (milton["played"], milton["lost"], milton["first_year"], milton["last_year"],
            milton["win_pct"], milton["rows"]) == (2, 2, 1888, 1892, 0.0, 2)
    totals = [{**t, "source_page": "p", "source_table": "s", "gender": "male", "format": "Test"}
              for t in C.parse_table(test)[1]]
    assert C.check_totals(totals, agg) == []
    flags = dict(zip(agg["name"], agg["page_total"]))
    assert (flags["William Milton"], flags["Ernest Halliwell"], flags["Owen Dunell"]) == (
        "match", "match", "")


def test_check_totals_reports_mismatch():
    test, _ = tables("captains_test_series.html")
    agg = C.aggregate(frame(test))
    _, totals = C.parse_table(test)
    totals = [{**t, "source_page": "p", "source_table": "s", "gender": "male", "format": "Test"}
              for t in totals]
    totals[0]["diff"] = {"played": (3, 2)}  # as if the page's Total row said 3
    issues = C.check_totals(totals, agg)
    assert issues == ["p | s | William Milton: played page 3 vs rows 2"]
    row = agg[agg["name"] == "William Milton"].iloc[0]
    assert (row["page_total"], row["page_total_detail"]) == ("mismatch", "played page 3 vs rows 2")


def test_ongoing_period_leaves_last_year_blank():
    odi, _ = tables("captains_odi.html")
    agg = C.aggregate(frame(odi, gender="female", format="ODI"))
    hm = agg[agg["name"] == "Hayley Matthews"].iloc[0]
    assert (hm["first_year"], hm["ongoing"]) == (2022, 1) and pd.isna(hm["last_year"])
    assert round(hm["win_pct"], 1) == 42.9


def test_fallback_cricsheet_requires_unique_surname_match():
    # synthetic article text and ids
    by_ci = {111: "aaaa0001", 222: "aaaa0002"}
    names = {"aaaa0001": "PL Mommsen", "aaaa0002": "CJ Mommsen"}
    page = {"title": "Preston Mommsen",
            "text": "x [http://www.cricinfo.com/scotland/content/player/111.html profile]"}
    assert C.fallback_cricsheet(page, by_ci, names) == "aaaa0001"
    page["text"] += " https://www.espncricinfo.com/player/c-mommsen-222"
    assert C.fallback_cricsheet(page, by_ci, names) is None  # two candidates: ambiguous
    page["text"] = ("{{Infobox cricketer\n| source = http://content-uk.cricinfo.com/ci/content/player/111.html\n}}"
                    + page["text"])
    assert C.fallback_cricsheet(page, by_ci, names) == "aaaa0001"  # infobox source wins
    assert C.fallback_cricsheet({"title": "Someone Else", "text": page["text"]}, by_ci, names) is None


def test_short_grand_total_in_one_row_table_is_right_aligned():
    (t,) = tables("captains_short_grand_total.html")
    assert C.classify(t, "international") == ("female", "ODI")
    rows, totals = C.parse_table(t)
    assert [r["name"] for r in rows] == ["Shaiza Khan", "Bismah Maroof"]
    (grand,) = totals
    assert grand["team_total"]
    assert (grand["played"], grand["won"], grand["tied"], grand["lost"], grand["no_result"]) == (
        168, 48, 1, 116, 3)


def _synthetic(header, *rows):
    # synthetic table, invented values
    th = "".join(f"<th>{h}</th>" for h in header)
    trs = "".join("<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>" for r in rows)
    html = (f"<h2>Men's cricket</h2><h3>Test match captains</h3>"
            f"<table class='wikitable'><tr>{th}</tr>{trs}</table>")
    (t,) = C.page_tables(html)
    return t


def test_short_total_left_aligned_when_counts_do_not_fill_the_span():
    # label spans the leading columns and the last count is missing
    t = _synthetic(["No.", "Name", "Year", "Played", "Won", "Tied", "Lost", "N/R"],
                   ["1", "A B", "2001", "5", "2", "0", "3", "0"])
    t["rows"].append([{"text": "Overall", "raw": "Overall", "links": [], "th": False}] * 3
                     + [{"text": v, "raw": v, "links": [], "th": False} for v in ("5", "2", "0", "3")])
    _, (tot,) = C.parse_table(t)
    assert (tot["played"], tot["won"], tot["tied"], tot["lost"], tot["no_result"]) == (5, 2, 0, 3, None)


def test_non_integer_count_cell_stays_blank_and_flags():
    # mirrors a NZ Test row whose Drawn cell holds a win percentage
    t = _synthetic(["Number", "Name", "Year(s)", "Opposition", "Location", "Played", "Won", "Lost",
                    "Drawn"],
                   ["21", "C D", "1990-91", "X", "Y", "1", "0", "0", "0.00"],
                   ["22", "E F", "1992-93", "X", "Y", "3", "1", "1", "0"])
    rows, _ = C.parse_table(t)
    cd, ef = rows
    assert (cd["played"], cd["won"], cd["lost"], cd["drawn"]) == (1, 0, 0, None)
    assert cd["notes"] == ""  # a blank count is unknown, not short
    assert ef["notes"] == "results short of played"
    assert C._int("-") is None and C._int(" 12 ") == 12 and C._int("45.5%") is None


def test_aggregate_blank_when_any_row_lacks_a_count():
    t = _synthetic(["Number", "Name", "Year(s)", "Opposition", "Location", "Played", "Won", "Lost",
                    "Drawn"],
                   ["1", "<a href='/wiki/G_H'>G H</a>", "2001", "X", "Y", "2", "1", "1", "0"],
                   ["1", "<a href='/wiki/G_H'>G H</a>", "2002", "X", "Y", "1", "", "", ""])
    agg = C.aggregate(frame(t))
    (g,) = agg.itertuples()
    assert (g.played, g.won, g.lost, g.drawn, g.win_pct) == (3, None, None, None, None)


def test_unclassifiable_table_is_reported():
    # synthetic: a captains table whose heading names no format
    html = ("<h2>Women's Captain</h2><table class='wikitable'><tr><th>No.</th><th>Name</th>"
            "<th>Played</th><th>Won</th><th>Lost</th></tr>"
            "<tr><td>1</td><td>A B</td><td>5</td><td>1</td><td>4</td></tr></table>")

    class W:
        def parse(self, title):
            return {"title": title, "revid": 1, "html": html}

    df, _, problems = C.collect(W(), [{"title": "P", "level": "international", "country": "X",
                                       "competition": "", "gender": ""}])
    assert df.empty
    assert problems == ["P: table \"Women's Captain\" skipped, format not inferable",
                        "P: no captain tables recognised"]


def test_list_page_matcher():
    assert C._is_list_page("List of South Africa national cricket captains", "South Africa")
    assert C._is_list_page("List of Indian Premier League captains", "Indian Premier League")
    assert not C._is_list_page("Lanka Premier League", "Lanka Premier League")
    assert not C._is_list_page("List of Durham cricket captains", "South Africa")
