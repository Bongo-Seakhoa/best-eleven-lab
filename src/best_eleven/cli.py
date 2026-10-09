"""best-eleven: gather the data, run the pipeline, pick an eleven, serve the site."""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import shutil
import socketserver
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import pipeline as pl

PRESETS = ["balanced", "quality", "form", "alltime", "legacy", "experience"]


def _select(args, p: pl.Paths) -> int:
    node = shutil.which("node")
    if not node:
        print("`select` runs the site's selection engine and needs Node.js 18+ on PATH.", file=sys.stderr)
        return 2
    scope_file = p.site_data / "scopes" / f"{args.scope}.json"
    if not scope_file.exists():
        print(f"No exported scope '{args.scope}'. Run `best-eleven build` first.", file=sys.stderr)
        return 2
    settings = {"scope": str(scope_file), "team": args.team, "from": args.from_year, "to": args.to_year,
                "availability": args.availability, "preset": args.preset, "fullOnly": not args.all_nations,
                "maxPerTeam": args.max_per_team, "maxOverseas": args.max_overseas}
    out = subprocess.run([node, str(p.site / "cli" / "select.mjs"), json.dumps(settings)],
                         capture_output=True, text=True)
    if out.returncode:
        print(out.stderr or out.stdout, file=sys.stderr)
        return out.returncode
    res = json.loads(out.stdout)
    if args.json:
        print(json.dumps(res, indent=1))
        return 0
    if "error" in res:
        print(f"No eleven: {res['error']}", file=sys.stderr)
        return 1
    print(f"\n{res['title']}\n{res['subtitle']}\n")
    for i, x in enumerate(res["xi"], 1):
        tags = " ".join(t for t in (x["captain"] and "(c)", x["keeper"] and "(wk)") if t)
        print(f"{i:>2}. {x['name']:<24} {x['slot']:<17} {x['team']:<22} {x['line']}  {tags}")
    if res.get("note"):
        print(f"\n{res['note']}")
    return 0


class _NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Local preview only: always revalidate, so edits show on reload."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def _serve(args, p: pl.Paths) -> int:
    handler = functools.partial(_NoCacheHandler, directory=str(p.site))
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Serving {p.site} at {url} (Ctrl+C to stop)")
        if args.open:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="best-eleven", description=__doc__)
    ap.add_argument("--root", default=".", help="project root (default: current directory)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download Cricsheet's archive and people register (conditional)")
    f.add_argument("--force", action="store_true")
    sub.add_parser("ingest", help="archive -> Parquet warehouse")
    e = sub.add_parser("enrich", help="refresh Wikipedia/Wikidata reference snapshots (network)")
    e.add_argument("--refresh", action="store_true", help="ignore the HTTP cache")
    sub.add_parser("model", help="run expectancy, adjusted values, aggregates, bowling-type model")
    sub.add_parser("validate", help="reconciliation and predictive checks")
    x = sub.add_parser("export", help="write site/data")
    x.add_argument("--no-profiles", action="store_true")
    sub.add_parser("build", help="ingest + model + validate + export (no network)")
    a = sub.add_parser("all", help="fetch + ingest + enrich + model + validate + export")
    a.add_argument("--skip-enrich", action="store_true")
    s = sub.add_parser("select", help="pick a Best XI from the exported data")
    s.add_argument("--scope", default="men-test", help="e.g. men-test, women-odi, ipl, sa20")
    s.add_argument("--team", default=None, help="exact team name; omit for a World / league-wide XI")
    s.add_argument("--from", dest="from_year", type=int, default=None)
    s.add_argument("--to", dest="to_year", type=int, default=None)
    s.add_argument("--availability", choices=["any", "active", "squad"], default="any")
    s.add_argument("--preset", choices=PRESETS, default="balanced")
    s.add_argument("--all-nations", action="store_true", help="include associate nations")
    s.add_argument("--max-per-team", type=int, default=None)
    s.add_argument("--max-overseas", type=int, default=None)
    s.add_argument("--json", action="store_true")
    v = sub.add_parser("serve", help="serve the site locally")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--open", action="store_true")
    args = ap.parse_args(argv)
    p = pl.Paths(args.root)
    if args.cmd == "fetch":
        pl.fetch(p, force=args.force)
    elif args.cmd == "ingest":
        pl.ingest(p)
    elif args.cmd == "enrich":
        pl.enrich(p, refresh=args.refresh)
    elif args.cmd == "model":
        pl.model(p)
    elif args.cmd == "validate":
        report = pl.validate(p)
        return 0 if all(c["passed"] for c in report["checks"]) else 1
    elif args.cmd == "export":
        pl.export(p, profiles=not args.no_profiles)
    elif args.cmd in ("build", "all"):
        if args.cmd == "all":
            pl.fetch(p)
        pl.ingest(p)
        if args.cmd == "all" and not args.skip_enrich:
            pl.enrich(p)
        pl.model(p)
        report = pl.validate(p)
        pl.export(p)
        failed = [c["name"] for c in report["checks"] if not c["passed"]]
        if failed:
            print("Validation failed: " + "; ".join(failed), file=sys.stderr)
            return 1
    elif args.cmd == "select":
        return _select(args, p)
    elif args.cmd == "serve":
        return _serve(args, p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
