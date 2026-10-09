import json
from pathlib import Path

import pytest

from best_eleven.enrich import players as P

FIX = Path(__file__).parent / "fixtures" / "enrich"


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ infobox
def test_infobox_men():
    row = P.parse_player(read("players_bavuma.wiki"), "Temba Bavuma")
    assert row["has_infobox"] == "1"
    assert row["birth_date"] == "1990-05-17"
    assert row["country"] == "South Africa"
    assert row["full_name"] == ""
    assert (row["batting_hand"], row["bowling_style_raw"]) == ("right", "Right-arm medium")
    assert (row["bowling_class"], row["bowling_family"], row["bowling_arm"]) == ("RM", "pace", "right")
    assert (row["role_raw"], row["role"]) == ("Middle-order batter", "middle-order batter")
    assert (row["international_span"], row["active_international"]) == ("2014-present", "1")
    assert (row["last_test_year"], row["last_odi_year"], row["last_t20i_year"]) == ("2025", "2026", "2023")
    assert (row["test_cap"], row["odi_cap"], row["t20i_cap"]) == ("320", "117", "83")
    assert row["stats_as_of"] == "4 October 2026"
    assert row["gender"] == "male"
    # "retired hurt" while batting is not a retirement
    assert row["retired_test"] == row["retired_international"] == row["retirement_evidence"] == ""
    career = json.loads(row["career_json"])
    assert list(career) == ["Test", "ODI", "T20I", "FC"]
    assert career["Test"] == {"matches": 66, "runs": 3810, "bat_avg": 38.1, "hundreds": 4, "fifties": 26,
                              "top_score": 172, "not_out": False, "balls": 96, "wickets": 1, "bowl_avg": 61.0,
                              "five_w": 0, "ten_w": 0, "best": "1/29", "catches": 32, "stumpings": None}
    assert career["ODI"]["bowl_avg"] is None and career["ODI"]["best"] is None
    assert career["T20I"]["balls"] is None and career["FC"]["runs"] == 10342


def test_infobox_women_labels_and_dash_template():
    row = P.parse_player(read("players_wolvaardt.wiki"), "Laura Wolvaardt")
    assert row["has_infobox"] == "1"  # "Infobox Cricketer" capitalised
    assert row["gender"] == "female"
    assert row["international_span"] == "2016-present" and row["active_international"] == "1"
    assert row["bowling_class"] == row["bowling_family"] == row["bowling_arm"] == ""
    career = json.loads(row["career_json"])
    assert list(career) == ["WTest", "WODI", "LA"]
    assert career["WTest"]["hundreds"] == 1 and career["WTest"]["balls"] is None
    assert career["WODI"]["runs"] == 5695


def test_career_not_out_other_columns_and_one_test():
    ib = {"column1": "[[Test cricket|Test]]", "top score1": "254*", "column2": "Youth Test",
          "column3": "[[Under-19 cricket|U19 ODI]]", "matches2": "3", "onetest": "yes", "testdebutyear": "1999"}
    career = P.career(ib)
    assert career["Test"]["top_score"] == 254 and career["Test"]["not_out"] is True
    assert career["other"]["label"] == "Youth Test" and career["other"]["matches"] == 3
    assert career["other_2"]["label"] == "U19 ODI"
    assert P._last_year(ib, "test") == "1999"


def test_spans_and_activity():
    assert P.active_international(["2004-2018"]) == "0"
    assert P.active_international(["2006-2009", "2009-present"]) == "1"
    assert P.active_international([]) == ""


def test_embedded_infobox_takes_personal_fields_from_host():
    text = ("{{Infobox officeholder\n| name = X\n| birth_date = {{Birth date|1908|8|27|df=yes}}\n"
            "| death_date = {{Death date and age|2001|2|25|1908|8|27|df=yes}}\n| module = {{Infobox cricketer\n"
            "| embed = yes\n| batting = Right-handed\n| bowling = Right-arm [[leg break]]\n}}\n}}")
    row = P.parse_player(text, "X")
    assert (row["birth_date"], row["death_date"]) == ("1908-08-27", "2001-02-25")
    assert row["batting_hand"] == "right" and row["bowling_class"] == "LB"


@pytest.mark.parametrize("value, expected", [
    ("{{Birth date and age|1990|5|17|df=y}}", "1990-05-17"),
    ("{{birth_date and age|1984|02|17|df=yes}}", "1984-02-17"),
    ("{{birth date and age|df=yes|1988|11|5}}", "1988-11-05"),
    ("{{Birth-date and age|5 November 1988}}", "1988-11-05"),
    ("17 May 1990", "1990-05-17"),
    ("{{Birth year and age|1990}}", ""),
    ("", ""),
])
def test_birth_dates(value, expected):
    assert P.parse_date(value) == expected


# ---------------------------------------------------------------- normalisers
@pytest.mark.parametrize("raw, expected", [
    ("Right-arm off break, Right-arm leg break", ("OB", "spin", "right")),
    ("Right-arm [[off break]]<br>Right-arm [[leg break]]", ("OB", "spin", "right")),
    ("Slow left-arm orthodox", ("SLA", "spin", "left")),
    ("Left-arm orthodox spin", ("SLA", "spin", "left")),
    ("Left-arm unorthodox spin", ("LWS", "spin", "left")),
    ("Slow left-arm chinaman", ("LWS", "spin", "left")),
    ("Left-arm wrist spin", ("LWS", "spin", "left")),
    ("Right-arm fast-medium", ("RFM", "pace", "right")),
    ("Right arm medium fast", ("RMF", "pace", "right")),
    ("Right-arm medium-fast", ("RMF", "pace", "right")),
    ("Right-arm fast", ("RF", "pace", "right")),
    ("Right-arm medium", ("RM", "pace", "right")),
    ("Right-arm slow-medium", ("RM", "pace", "right")),
    ("Left-arm fast-medium", ("LFM", "pace", "left")),
    ("Left-arm medium", ("LM", "pace", "left")),
    ("Legbreak googly", ("LB", "spin", "right")),
    ("Leg break googly", ("LB", "spin", "right")),
    ("Right-arm off spin", ("OB", "spin", "right")),
    ("Right-arm fast-medium (off-cutters)", ("RFM", "pace", "right")),
    ("Medium-fast", ("", "pace", "")),
    ("Right-arm", ("", "", "right")),
    ("", ("", "", "")),
])
def test_bowling_normaliser(raw, expected):
    from best_eleven.enrich.wiki import strip_markup
    assert P.bowling(strip_markup(raw)) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Batsman", "batter"),
    ("[[Batting (cricket)|Batter]]", "batter"),
    ("Opening batsman", "opening batter"),
    ("Top-order batter", "top-order batter"),
    ("Middle-order batter", "middle-order batter"),
    ("[[Wicket-keeper-batter]]", "wicket-keeper-batter"),
    ("Wicketkeeper-batsman", "wicket-keeper-batter"),
    ("Wicket-keeper", "wicket-keeper"),
    ("Batter, occasional wicket-keeper", "batter"),
    ("Batting all-rounder", "batting all-rounder"),
    ("[[Bowling All-rounder]]", "bowling all-rounder"),
    ("Allrounder", "all-rounder"),
    ("[[Bowling (cricket)|Bowler]]", "bowler"),
    ("Captain", ""),
])
def test_role_normaliser(raw, expected):
    from best_eleven.enrich.wiki import strip_markup
    assert P.role(strip_markup(raw)) == expected


def test_batting_hand_and_country():
    assert P.batting_hand("Left-handed") == "left"
    assert P.batting_hand("") == ""
    assert P.country_name("{{flagicon|USA}} [[United States national cricket team|United States]]") == \
        "United States of America"
    assert P.country_name("{{cr|UAE}}") == "United Arab Emirates"


# ---------------------------------------------------------------- retirement
def retire(text, *names):
    return P.detect_retirement(text, names)


def test_retirement_kohli_formats_and_other_subjects():
    r = retire(read("players_kohli_excerpt.wiki"), "Virat Kohli")
    assert (r["retired_test"], r["retired_t20i"]) == ("1", "1")
    # Tendulkar's retirement, Dhoni's retirement and the external-link title are not Kohli's
    assert r["retired_odi"] == r["retired_international"] == ""
    assert "retirement from T20Is" in r["retirement_evidence"]
    assert len(r["retirement_evidence"]) <= 200


def test_retirement_comeback_restores_earlier_state():
    r = retire(read("players_bravo_excerpt.wiki"), "Dwayne Bravo")
    assert (r["retired_test"], r["retired_odi"], r["retired_t20i"], r["retired_international"]) == ("1", "", "", "")


@pytest.mark.parametrize("text, expected", [
    ("On 23 May 2018, de Villiers announced his retirement from all forms of international cricket.", "toti"),
    ("He announced his retirement from IPL on 19 November 2021.", "...."),
    ("On 10 July, de Villiers kept wicket after Mark Boucher announced retirement from cricket.", "...."),
    ("Steyn announced his retirement from all forms of cricket on 31 August 2021.", "toti"),
    ("He retired from first-class cricket in 2010.", "...."),
    ("She retired from ODI and T20I cricket in 2022.", ".ot."),
    ("He retired from limited-overs international cricket.", ".ot."),
    ("He was persuaded not to retire from Test cricket.", "...."),
    ("He denied rumours that he was retiring from Test cricket.", "...."),
    ("In May 2025 he announced his retirement from Test cricket.", "t..."),
    ("He stepped down from the Test captaincy and retired from Test captaincy duties.", "...."),
    ("In 2022 he retired from ODIs, but in 2023 he came out of ODI retirement for the World Cup.", "...."),
    ("On 5 August 2019, Steyn announced his retirement from Test cricket, to focus on limited-overs cricket.",
     "t..."),
    ("Following his Test retirement, he played on in white-ball cricket.", "t..."),
    ("He retired hurt in the second Test.", "...."),
    ("His father retired from international cricket in 1990.", "...."),
])
def test_retirement_phrases(text, expected):
    r = retire(text, "AB de Villiers", "Dale Steyn")
    got = "".join(k[8] if r[k] else "." for k in ("retired_test", "retired_odi", "retired_t20i",
                                                    "retired_international"))
    assert got == expected


@pytest.mark.parametrize("text", [
    "He announced his retirement from professional cricket in September 2023 although he has continued to play "
    "for Italy.",
    "In March 2020, Piedt announced his retirement from cricket in South Africa, and later moved to the United States.",
    "He retired from all forms of cricket but continued to play for Scotland in international matches.",
])
def test_retirement_all_cricket_guards(text):
    assert retire(text, "Gareth Berg", "Dane Piedt")["retired_international"] == ""


def test_retirement_bare_decision_reversal():
    text = ("In July 2022, Dottin announced her retirement from international cricket. "
            "She reversed her decision on July 27, 2024, saying she was eager to return.")
    assert retire(text, "Deandra Dottin")["retired_international"] == ""
    # a reversal far from any retirement statement is ignored
    text = ("In July 2022, Dottin announced her retirement from international cricket.\n\nShe joined a league.\n\n"
            "She coached juniors.\n\nShe played in Australia.\n\nShe reversed her decision on the captaincy in 2024.")
    assert retire(text, "Deandra Dottin")["retired_international"] == "1"


def test_retirement_superseded_by_later_appearances():
    text = "In September 2021, Taylor announced that he would retire from international cricket following the match."
    r = P.detect_retirement(text, ["Brendan Taylor"], {"test": "2025", "odi": "2026", "t20i": "2026"})
    assert r["retired_international"] == r["retired_odi"] == r["retirement_evidence"] == ""
    r = P.detect_retirement(text, ["Brendan Taylor"], {"test": "2021", "odi": "2021", "t20i": "2021"})
    assert r["retired_international"] == "1"


def test_retirement_ordering_by_year_not_position():
    text = ("He came out of ODI retirement in 2023.\n\n"
            "Smith retired from ODI cricket in 2022.")
    assert retire(text, "Steve Smith")["retired_odi"] == ""


def test_article_sentences_drop_tables_refs_and_templates():
    text = ("Intro {{nowrap|text}} here.<ref>{{cite web|title=He retired from Test cricket}}</ref> Next one.\n"
            "{| class=\"wikitable\"\n|-\n| He retired from Test cricket\n|}\n"
            "[[File:X.jpg|thumb|He retired from [[Test cricket]]]]\n== References ==\nHe retired from Tests.\n")
    assert P.article_sentences(text) == ["Intro text here.", "Next one."]
