"""Portable entry point: fetch → validate → analyse → select → inspect."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import date
from pathlib import Path
import json
import sys
from .analytics import Scope, rankings, player_profile, coverage
from .store import connect
from .sources import SOURCES, fetch_source
from .selection import Preferences, select_eleven, sensitivity, why_not
from .util import dumps


def main(argv=None):
    p = argparse.ArgumentParser(prog="best-eleven", description="Cricket selection and player diagnostics. National teams first.")
    p.add_argument("--db", default="data/best-eleven.sqlite", help="Local SQLite path")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("sources")
    sub.add_parser("coverage")
    demo = sub.add_parser("demo"); demo.add_argument("--matches-per-format", type=int, default=36)
    fetch = sub.add_parser("fetch"); fetch.add_argument("source", choices=SOURCES); fetch.add_argument("--force", action="store_true")
    ingest = sub.add_parser("ingest"); ingest.add_argument("archive"); ingest.add_argument("--source", required=True); ingest.add_argument("--provenance", required=True)
    meta = sub.add_parser("metadata"); meta.add_argument("csv")
    serve = sub.add_parser("serve"); serve.add_argument("--port", type=int, default=8765); serve.add_argument("--open", action="store_true")
    for name in ("rank", "select", "profile", "sensitivity", "evaluate", "fantasy", "why-not", "export-preview"):
        a = sub.add_parser(name)
        a.add_argument("--format", choices=["Test", "ODI", "T20"], default="Test")
        a.add_argument("--gender", choices=["male", "female"], default="male")
        a.add_argument("--level", choices=["international", "club"], default="international")
        a.add_argument("--competition", default=""); a.add_argument("--team", default="")
        a.add_argument("--since", default="2000-01-01"); a.add_argument("--as-of", default=date.today().isoformat())
        a.add_argument("--dataset", choices=["real", "demo"], default="real")
        a.add_argument("--half-life-days", type=float, default=730)
        a.add_argument("--output")
        if name in {"select", "sensitivity", "why-not", "fantasy"}:
            a.add_argument("--preferences", help="JSON file with Preferences fields")
        if name in {"profile", "why-not"}:
            a.add_argument("player_id")
        if name == "fantasy":
            a.add_argument("--rules", help="JSON FantasyRules file")
    args = p.parse_args(argv)
    try:
        if args.command == "serve":
            from .app import create_app
            import uvicorn
            if args.open:
                import threading, webbrowser
                threading.Timer(1, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
            uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port)
            return 0
        db = connect(args.db)
        if args.command == "sources":
            result = [{**asdict(s), "url": s.url} for s in SOURCES.values()]
        elif args.command == "demo":
            from .demo import make_demo
            result = make_demo(db, args.matches_per_format)
        elif args.command == "fetch":
            result = fetch_source(db, args.source, Path(args.db).parent / "raw", force=args.force)
        elif args.command == "ingest":
            from .sources import import_source_archive
            result = import_source_archive(db, args.archive, args.source, args.provenance, Path(args.db).parent / "raw")
        elif args.command == "metadata":
            from .metadata import import_metadata
            result = import_metadata(db, args.csv)
        elif args.command == "coverage":
            result = coverage(db)
        else:
            scope = Scope(**{k: getattr(args, k) for k in asdict(Scope())})
            pref = Preferences(**json.loads(Path(args.preferences).read_text())) if getattr(args, "preferences", None) else Preferences(min_bowling_options=4 if scope.format == "Test" else 5)
            if args.command == "evaluate":
                from .evaluate import rolling_evaluate
                result = rolling_evaluate(db, scope)
            elif args.command == "export-preview":
                from .preview import export_preview
                result = export_preview(db, args.output or "best-eleven-preview.html", scope)
            else:
                ranking = rankings(db, scope)
                if args.command == "rank":
                    result = ranking
                elif args.command == "select":
                    result = select_eleven(ranking, pref)
                elif args.command == "sensitivity":
                    result = sensitivity(ranking, pref)
                elif args.command == "profile":
                    result = player_profile(db, scope, args.player_id, ranking)
                elif args.command == "why-not":
                    result = why_not(ranking, args.player_id, pref)
                elif args.command == "fantasy":
                    from .fantasy import FantasyRules, fantasy_projection, fantasy_captains
                    rules = FantasyRules(**json.loads(Path(args.rules).read_text())) if args.rules else FantasyRules()
                    projections = fantasy_projection(db, scope, rules)
                    values = {r["player_id"]: r["expected_points"] for r in projections["players"]}
                    xi = select_eleven(ranking, pref, fantasy_values=values)
                    result = {"projections": projections, "selection": xi, "multipliers": fantasy_captains(xi["eleven"], values, rules)}
        db.close()
        text = dumps(result, indent=2)
        if getattr(args, "output", None) and args.command != "export-preview":
            out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(text, encoding="utf-8")
        else:
            print(text)
        if result.get("status") in {"partial", "infeasible"} if isinstance(result, dict) else False:
            return 2
        return 0
    except (ValueError, TypeError, RuntimeError, OSError, KeyError) as exc:
        print(f"best-eleven: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
