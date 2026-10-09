"""Squad parsing on saved Wikipedia HTML (network-free)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from lxml import html as lh

from best_eleven.enrich import squads as S

FIX = Path(__file__).parent / "fixtures" / "enrich"


def rows(name, **kw):
    return {r["name"]: r for r in S.squad_rows((FIX / name).read_text(encoding="utf-8"), **kw)}


def test_national_sa_squad():
    r = rows("squads_national_sa.html")
    # coaching-staff and post-heading tables are excluded
    assert list(r) == ["Temba Bavuma", "David Bedingham", "David Miller", "Aiden Markram", "Kagiso Rabada"]
    b = r["Temba Bavuma"]
    assert (b["forms"], b["captain_formats"], b["vice_captain_formats"], b["captain"]) == ("Test;ODI", "Test;ODI", "", "C")
    assert (b["role_group"], b["contracted"], b["domestic_team"], b["shirt_number"]) == ("batter", "1", "Lions", "11")
    assert (b["wikipedia_title"], b["title_basis"]) == ("Temba Bavuma", "link")
    assert (b["last_test"], b["last_odi"], b["last_t20i"]) == ("2025", "2025", "2023")
    assert b["bowling_style"] == "Right-arm medium" and b["overseas"] == ""
    m = r["Aiden Markram"]
    assert (m["captain_formats"], m["vice_captain_formats"], m["role_group"]) == ("T20I", "Test;ODI", "all-rounder")
    assert r["David Bedingham"]["contracted"] == "0"  # N/a in the contract column
    assert r["David Bedingham"]["league_teams"] == "SA20 Team: Sunrisers Eastern Cape"
    assert r["David Bedingham"]["bowling_style"] == ""  # N/a cell
    assert r["David Miller"]["wikipedia_title"] == "David Miller (South African cricketer)"
    assert r["David Miller"]["vice_captain_formats"] == "T20I"
    assert r["Kagiso Rabada"]["role_group"] == "pace bowler"  # "Seam bowlers" group


def test_group_row_with_leading_empty_cell_and_name_marker():
    r = rows("squads_national_india_women.html")
    assert list(r) == ["Harmanpreet Kaur", "Smriti Mandhana", "Deepti Sharma"]
    assert r["Deepti Sharma"]["role_group"] == "all-rounder"
    assert r["Smriti Mandhana"]["captain"] == "C" and r["Smriti Mandhana"]["captain_formats"] == ""
    assert r["Harmanpreet Kaur"]["forms"] == "Test;ODI;T20I"  # "Test, ODI & T20I"
    assert r["Harmanpreet Kaur"]["contracted"] == ""  # no contract column


def test_format_captain_in_remarks():
    r = rows("squads_national_nepal.html")
    assert r["Dipendra Singh Airee"]["captain_formats"] == "T20I"
    assert r["Sandeep Lamichhane"]["captain_formats"] == "ODI"
    assert r["Sandeep Lamichhane"]["contracted"] == "1"  # grade "A+"
    assert r["Sandeep Lamichhane"]["league_teams"] == "NPL: Biratnagar Kings"
    assert r["Sandeep Lamichhane"]["role_group"] == "spin bowler"


def test_franchise_overseas_from_notes():
    r = rows("squads_franchise_mi.html", home={"India"})
    assert [r[n]["overseas"] for n in r] == ["0", "0", "1", "1"]
    assert {x["overseas_basis"] for x in r.values()} == {"note"}
    assert "overseas" in r["Quinton de Kock"]["overseas_legend"].lower()
    assert r["Quinton de Kock"]["nationality"] == "South Africa"
    assert r["Quinton de Kock"]["role_group"] == "wicket-keeper"
    assert r["Suryakumar Yadav"]["captain"] == "VC"  # notes: "vice Captain"
    assert r["Rohit Sharma"]["forms"] == "" and r["Rohit Sharma"]["captain_formats"] == ""


def test_franchise_overseas_from_nationality_column():
    r = rows("squads_franchise_psl.html", home={"Pakistan"})
    lab = r["Marnus Labuschagne"]
    assert (lab["nationality"], lab["overseas"], lab["overseas_basis"]) == ("Australia", "1", "nationality")
    assert lab["captain"] == "C"
    assert r["Sharjeel Khan"]["overseas"] == "0"
    assert (r["Tayyab Arif"]["wikipedia_title"], r["Tayyab Arif"]["title_basis"]) == ("", "")


def test_without_home_country_nationality_does_not_set_overseas():
    r = rows("squads_franchise_psl.html")
    assert {x["overseas"] for x in r.values()} == {""}


def test_redlink_plain_text_and_captain_paragraph():
    r = rows("squads_franchise_srh.html", home={"India"})
    assert (r["Amit Kumar"]["wikipedia_title"], r["Amit Kumar"]["title_basis"]) == ("", "redlink")
    assert (r["Smaran Ravichandran"]["wikipedia_title"], r["Smaran Ravichandran"]["title_basis"]) == ("", "")
    assert r["Pat Cummins"]["captain"] == "C" and r["Pat Cummins"]["overseas"] == "1"
    assert r["Travis Head"]["nationality"] == "Australia"  # from the flag link only


def test_season_article_team_columns():
    html = (FIX / "squads_season_cpl.html").read_text(encoding="utf-8")
    ab = S.season_team_rows(html, "Antigua and Barbuda Falcons", "Antigua & Barbuda Falcons")
    assert [x["name"] for x in ab] == ["Moeen Ali", "Alzarri Joseph", "Amir Jangoo", "Anderson Mahase"]
    assert ab[0]["captain"] == "C" and ab[0]["wikipedia_title"] == "Moeen Ali"
    assert (ab[3]["wikipedia_title"], ab[3]["title_basis"]) == ("", "")
    bt = S.season_team_rows(html, "Barbados Tridents", "Barbados Tridents")
    assert bt[0]["wikipedia_title"] == "Chris Green (cricketer)"
    assert S.season_team_rows(html, "Jamaica Kingsmen", "Jamaica Kingsmen") == []


def test_season_article_country_code_marks_overseas():
    html = ('<table class="wikitable"><tr><th>Sydney Sixers</th><th>Sydney Thunder</th></tr>'
            '<tr><td><ul><li><a href="/wiki/A_One">A One</a> (c)</li>'
            '<li><a href="/wiki/B_Two">B Two</a> (<a href="/wiki/England_cricket_team">ENG</a>)</li></ul></td>'
            '<td><ul><li>C Three</li></ul></td></tr></table>')
    got = S.season_team_rows(html, "Sydney Sixers", "Sydney Sixers (WBBL)")
    assert [(x["name"], x["overseas"], x["nationality"], x["captain"]) for x in got] == [
        ("A One", "0", "", "C"), ("B Two", "1", "England", "")]
    assert got[1]["wikipedia_title"] == "B Two"


@pytest.mark.parametrize("text,expected", [
    ("Test, ODI (C)", (["Test", "ODI"], [], "C")),
    ("T20I (C); Test, ODI (VC)", (["T20I"], ["Test", "ODI"], "C")),
    ("ODI, T20I (C), Test (VC)", (["ODI", "T20I"], ["Test"], "C")),
    ("ODI (VC), T20I (C)", (["T20I"], ["ODI"], "C")),
    ("T20I (c) ODI (VC)", (["T20I"], ["ODI"], "C")),
    ("Test(C)", (["Test"], [], "C")),
    ("ODI, T20I (VC)", ([], ["ODI", "T20I"], "VC")),
    ("T20I Captain", (["T20I"], [], "C")),
    ("ODI vice-captain", ([], ["ODI"], "VC")),
    ("Vice-captain", ([], [], "VC")),
    ("Captain", ([], [], "C")),
    ("(C)", ([], [], "C")),
    ("Overseas", ([], [], "")),
    ("", ([], [], "")),
])
def test_parse_captaincy(text, expected):
    assert S.parse_captaincy(text) == expected


def test_vocab_helpers():
    assert S.parse_forms("Test, ODI & T20I") == ["Test", "ODI", "T20I"]
    assert S.parse_forms("T20Is, Tests") == ["Test", "T20I"]
    assert S.parse_forms("") == []
    assert [S.role_group(x) for x in ["Batsmen", "All Rounders", "Wicket-keeper-batters", "Spin Bowlers",
                                      "Seam bowlers", "Fast Bowlers", "Bowlers", "Captain"]] == [
        "batter", "all-rounder", "wicket-keeper", "spin bowler", "pace bowler", "pace bowler", "bowler", ""]
    assert S.split_markers("Moeen Ali (c)") == ("Moeen Ali", ["c"])
    assert S.split_markers("Maia Bouchier ( ENG )") == ("Maia Bouchier", ["ENG"])
    assert S.split_markers("Kane Williamson†") == ("Kane Williamson", ["†"])
    assert S.country("United States national cricket team") == "United States of America"
    assert S.country("India women's national cricket team") == "India"
    assert S.country("England cricket team") == "England"
    assert S.season_labels("split", dt.date(2026, 10, 9)) == ["2026–27", "2025–26"]
    assert S.season_labels("year", dt.date(2026, 10, 9)) == ["2027", "2026"]


def test_pick_sections_prefers_current_squad():
    bangladesh = [{"index": "34", "level": "2", "line": "Players"},
                  {"index": "35", "level": "2", "line": "Current squad"},
                  {"index": "58", "level": "3", "line": "By Bangladeshi players"}]
    assert [s["index"] for s in S.pick_sections(bangladesh)] == ["35", "34"]
    sa = [{"index": "29", "level": "2", "line": "Current squad"},
          {"index": "32", "level": "2", "line": "Current and former players"}]
    assert [s["index"] for s in S.pick_sections(sa)] == ["29"]
    gg = [{"index": "10", "level": "3", "line": "Gujarat Giants WPL 2026 Squad (The New Roster)"},
          {"index": "12", "level": "2", "line": "Support staff"}]
    assert [s["index"] for s in S.pick_sections(gg)] == ["10"]
    assert S.pick_sections([{"index": "5", "level": "2", "line": "Former players"}]) == []


def test_grid_rowspan_and_colspan():
    t = lh.fromstring('<table><tr><th>Name</th><th>Bat</th><th>Last Test</th></tr>'
                      '<tr><td>A</td><td>Right-handed</td><td rowspan="2">2025</td></tr>'
                      '<tr><td>B</td><td>Left-handed</td></tr>'
                      '<tr><th colspan="3">Bowlers</th></tr>'
                      '<tr><td>C</td><td colspan="2">Right-handed</td></tr></table>')
    header, body = S.table_rows(t)
    assert header == ["Name", "Bat", "Last Test"]
    assert [(S.cell_text(r["cells"]["Name"]), S.cell_text(r["cells"]["Last Test"]), r["group"]) for r in body] == [
        ("A", "2025", ""), ("B", "2025", ""), ("C", "Right-handed", "Bowlers")]


def test_is_squad_table_rejects_staff_and_record_tables():
    assert S.is_squad_table(["Name", "Age", "Batting style", "Bowling style"])
    assert not S.is_squad_table(["Position", "Name", "Nationality"])
    assert not S.is_squad_table(["Player", "Nationality", "From", "To", "Matches", "Won"])
    assert not S.is_squad_table(["Symbol", "Meaning"])
