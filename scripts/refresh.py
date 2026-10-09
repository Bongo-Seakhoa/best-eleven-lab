"""Explicit, single-source refresh for a local run or manually dispatched CI job."""
from dataclasses import asdict
from datetime import date
from pathlib import Path
import argparse
from best_eleven.sources import SOURCES, fetch_source
from best_eleven.store import connect
from best_eleven.analytics import Scope, rankings, coverage
from best_eleven.selection import select_eleven
from best_eleven.util import dumps

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',choices=SOURCES,required=True)
parser.add_argument('--format',choices=['Test','ODI','T20'],required=True)
parser.add_argument('--team',default='')
parser.add_argument('--gender',choices=['male','female'],default='male')
parser.add_argument('--level',choices=['international','club'],default='international')
parser.add_argument('--as-of',default=date.today().isoformat())
parser.add_argument('--db',default='data/best-eleven.sqlite')
parser.add_argument('--output',default='results')
args=parser.parse_args()
out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
db=connect(args.db)
try:
    receipt=fetch_source(db,args.source,Path(args.db).parent/'raw')
    (out/'acquisition.json').write_text(dumps(receipt,indent=2))
    (out/'coverage.json').write_text(dumps(coverage(db),indent=2))
    if receipt['status']=='partial':raise SystemExit('Partial ingestion: inspect acquisition.json before selection')
    scope=Scope(format=args.format,team=args.team,gender=args.gender,level=args.level,as_of=args.as_of)
    ranking=rankings(db,scope);selection=select_eleven(ranking)
    (out/'ranking.json').write_text(dumps(ranking,indent=2))
    (out/'selection.json').write_text(dumps(selection,indent=2))
    if selection['status']=='infeasible':raise SystemExit('No valid XI under the declared evidence and role constraints; see selection.json')
finally:
    db.close()
