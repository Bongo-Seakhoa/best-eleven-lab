"""A portable, offline view built from the same UI and Python selection engine."""
from dataclasses import asdict, replace
from pathlib import Path
from .analytics import Scope, rankings, player_profile, coverage
from .selection import Preferences, select_eleven, sensitivity
from .evaluate import rolling_evaluate
from .sources import SOURCES
from .util import dumps


def export_preview(db, destination, scope: Scope):
    if scope.dataset != "demo":
        raise ValueError("The portable preview is deliberately restricted to synthetic data. Use the local app for real records.")
    if not scope.team:
        raise ValueError("Choose one fictional team for the preview")
    payload = {"provenance": "SYNTHETIC: invented players, teams and outcomes; no real-player findings", "team": scope.team,
               "as_of": scope.as_of, "coverage": coverage(db), "sources": [{**asdict(s), "url": s.url} for s in SOURCES.values()], "formats": {}}
    # A demo export must not carry live records, source errors or local archive paths.
    payload["coverage"]["groups"] = [r for r in payload["coverage"]["groups"] if r["is_synthetic"]]
    payload["coverage"]["teams"] = [r for r in payload["coverage"]["teams"] if r["is_synthetic"]]
    payload["coverage"]["fetches"] = []
    payload["coverage"]["errors"] = []
    payload["coverage"]["deliveries"] = db.execute("SELECT COUNT(*) FROM deliveries d JOIN matches m ON m.id=d.match_id WHERE m.is_synthetic=1").fetchone()[0]
    payload["coverage"]["players"] = db.execute("SELECT COUNT(DISTINCT a.player_id) FROM appearances a JOIN matches m ON m.id=a.match_id WHERE m.is_synthetic=1").fetchone()[0]
    for format_ in ("Test", "ODI", "T20"):
        current = replace(scope, format=format_)
        ranking = rankings(db, current)
        pref = Preferences(min_bowling_options=4 if format_ == "Test" else 5)
        payload["formats"][format_] = {
            "ranking": ranking,
            "scenarios": {str(e): select_eleven(ranking, replace(pref, performance=100-e, experience=e)) for e in (0, 15, 25, 40)},
            "sensitivity": sensitivity(ranking, pref),
            "profiles": {p["id"]: player_profile(db, current, p["id"], ranking) for p in ranking["players"]}}
    payload["evaluation"] = rolling_evaluate(db, replace(scope, format="Test", team=""))
    web = Path(__file__).parent / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="/assets/style.css">', '<style>' + (web / "style.css").read_text(encoding="utf-8") + '</style>')
    html = html.replace('<!-- PACK -->', '<script>window.BEST_ELEVEN_PACK=' + dumps(payload).replace('<', '\\u003c') + ';</script>')
    html = html.replace('<script src="/assets/app.js"></script>', '<script>' + (web / "app.js").read_text(encoding="utf-8") + '</script>')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return {"output": str(destination), "provenance": payload["provenance"], "formats": list(payload["formats"]), "bytes": destination.stat().st_size}
