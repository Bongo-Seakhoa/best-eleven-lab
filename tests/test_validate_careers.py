"""Career totals vs Wikipedia (src/best_eleven/validate.py career_check), on a synthetic warehouse.

The matches and players below are invented to test the date logic; they are not cricket records.
"""
import json

import pandas as pd
import pytest

from best_eleven.validate import career_check, infobox_date

SNAPSHOT = "2026-10-09T12:00:00+00:00"
# Three South Africa Tests: two before the snapshot, one after it.
TESTS = {1: ("2026-01-01", "2026-01-05"), 2: ("2026-09-01", "2026-09-05"), 3: ("2026-10-12", "2026-10-16")}


def build(tmp_path, wiki_rows, tests=TESTS, played=None, manifest=True):
    """Warehouse, season aggregates and reference snapshot for South African Test players.
    Every player scores 10 runs and takes 1 wicket in each Test he plays."""
    wh, md, ref = tmp_path / "warehouse", tmp_path / "model", tmp_path / "reference"
    for d in (wh, md / "seasons", ref):
        d.mkdir(parents=True)
    ids = [r["id"] for r in wiki_rows]
    played = played or {pid: list(tests) for pid in ids}
    num = {pid: i + 1 for i, pid in enumerate(ids)}
    old = 999   # an early player, so coverage starts well before everyone else's debut
    matches = [{"match_id": k, "scope": "men-test", "start_date": s, "end_date": e} for k, (s, e) in tests.items()]
    matches.append({"match_id": 900, "scope": "men-test", "start_date": "2002-01-01", "end_date": "2002-01-05"})
    pm = [{"match_id": k, "player": num[pid]} for pid, ks in played.items() for k in ks] + [{"match_id": 900, "player": old}]
    pd.DataFrame(matches).to_parquet(wh / "matches.parquet")
    pd.DataFrame(pm).to_parquet(wh / "appearances.parquet")
    pd.DataFrame(pm).assign(runs=10, super_over=0).to_parquet(wh / "batting.parquet")
    pd.DataFrame(pm).assign(wickets=1, super_over=0).to_parquet(wh / "bowling.parquet")
    pd.DataFrame({"player": list(num.values()) + [old], "id": ids + ["old"]}).to_parquet(wh / "players.parquet")
    years = pd.DataFrame(matches).assign(year=lambda d: d["start_date"].str[:4].astype(int))[["match_id", "year"]]
    s = pd.DataFrame(pm).merge(years, on="match_id").groupby(["player", "year"]).size().rename("m").reset_index()
    s = s.assign(team="South Africa", r=10 * s["m"], ww=s["m"])
    s.to_parquet(md / "seasons" / "men-test.parquet")
    for scope in ("men-odi", "men-t20i"):
        pd.DataFrame({"player": [old], "year": [2005], "team": ["South Africa"], "m": [1], "r": [0], "ww": [0]}).to_parquet(
            md / "seasons" / f"{scope}.parquet")
    rows = [{"cricsheet_id": r["id"], "stats_as_of": r["as_of"],
             "career_json": json.dumps({"Test": {"matches": r["m"], "runs": r["r"], "wickets": r["w"]}})} for r in wiki_rows]
    pd.DataFrame(rows).to_csv(ref / "players_wiki.csv", index=False)
    if manifest:
        (ref / "manifest.json").write_text(json.dumps({"fetched_at": SNAPSHOT}), encoding="utf-8")
    return md, wh, ref


def player(pid, as_of="4 October 2026", m=2, r=20, w=2):
    return {"id": pid, "as_of": as_of, "m": m, "r": r, "w": w}


def test_matches_after_the_infobox_date_are_not_counted(tmp_path):
    # Infoboxes as of 4 October count the first two Tests; Cricsheet also has the third.
    res = career_check(*build(tmp_path, [player(f"p{i}") for i in range(5)]), min_strict=5)
    assert res["passed"], res["summary"]
    assert res["strict"] == {**res["strict"], "players": 5, "exact": 1.0, "mismatches": []}


def test_a_real_gap_still_fails(tmp_path):
    rows = [player(f"p{i}") for i in range(5)] + [player("short", r=25)]   # infobox has 5 runs Cricsheet lacks
    res = career_check(*build(tmp_path, rows), min_strict=5)
    assert not res["passed"]
    assert res["strict"]["exact"] == pytest.approx(5 / 6, abs=1e-4)
    assert [x["id"] for x in res["strict"]["mismatches"]] == ["short"]


def test_strict_set_does_not_shrink_as_data_grows(tmp_path):
    # A year after the snapshot the same infoboxes are still checked: freshness is
    # measured from the snapshot, not from the latest match.
    tests = {**TESTS, 4: ("2027-12-01", "2027-12-05")}
    res = career_check(*build(tmp_path, [player(f"p{i}") for i in range(5)], tests=tests), min_strict=5)
    assert res["passed"], res["summary"]
    assert res["strict"]["players"] == 5


def test_infobox_dated_inside_a_match_is_left_out(tmp_path):
    rows = [player(f"p{i}") for i in range(5)] + [player("mid", as_of="3 September 2026", m=1, r=10, w=1)]
    res = career_check(*build(tmp_path, rows), min_strict=5)
    assert res["strict"]["players"] == 5
    assert res["strict"]["left_out_inside_a_match"] == 1


def test_infobox_dated_after_the_data_is_left_out(tmp_path):
    # Without the October Test the data ends on 5 September; an infobox as of 4 October
    # may hold matches Cricsheet has not published, so it cannot be judged yet.
    tests = {k: v for k, v in TESTS.items() if k != 3}
    rows = [player(f"p{i}", as_of="5 September 2026") for i in range(5)] + [player("ahead")]
    res = career_check(*build(tmp_path, rows, tests=tests), min_strict=5)
    assert res["passed"], res["summary"]
    assert res["strict"]["players"] == 5


def test_stale_and_undated_infoboxes_are_not_in_the_strict_set(tmp_path):
    rows = [player(f"p{i}") for i in range(5)] + [player("stale", as_of="1 June 2026", m=1, r=10, w=1),
                                                 player("monthly", as_of="October 2026"), player("blank", as_of="")]
    res = career_check(*build(tmp_path, rows), min_strict=5)
    assert res["strict"]["players"] == 5


def test_too_few_strict_players_fails(tmp_path):
    res = career_check(*build(tmp_path, [player(f"p{i}") for i in range(4)]), min_strict=5)
    assert not res["passed"]


def test_infobox_dated_after_the_snapshot_is_not_in_the_strict_set(tmp_path):
    rows = [player(f"p{i}") for i in range(5)] + [player("future", as_of="16 October 2026", m=3, r=30, w=3)]
    res = career_check(*build(tmp_path, rows), min_strict=5)
    assert res["passed"], res["summary"]
    assert res["strict"]["players"] == 5


def test_missing_snapshot_date_fails(tmp_path):
    res = career_check(*build(tmp_path, [player(f"p{i}") for i in range(5)], manifest=False), min_strict=5)
    assert not res["passed"]
    assert "snapshot" in res["summary"]


@pytest.mark.parametrize("text, want", [
    ("4 October 2026", "2026-10-04"), ("August 9, 2025", "2025-08-09"), ("23 February, 2016", "2016-02-23"),
    ("19 Nov 2024", "2024-11-19"), ("  4  October 2026 ", "2026-10-04"),
    ("October 2012", None), ("2013", None), ("31 November 2013", None), ("8 July Lop 2025", None), ("", None),
])
def test_infobox_date(text, want):
    got = infobox_date(text)
    assert (pd.isna(got) if want is None else got == pd.Timestamp(want))
