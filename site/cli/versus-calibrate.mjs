// Projected edge of real matches, for calibrating XI vs XI win chances
// (used by `best-eleven calibrate`). Runs the site's own engine: nothing here
// restates a rating or projection formula.
//
//   node versus-calibrate.mjs <input.json> <output.json>
//
// input: {scopesDir, groups (versus.json "groups"), window, halfLife,
//         matches: [{id, scope, year, a: [cricsheet ids in batting order], b: [...]}]}
// output: [{id, key, edge, scoreA, scoreB, rated: [a, b]}], where `rated` counts
// the players in each side with a record in the window.
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { aggregate, SUM_COLS } from '../assets/js/engine/aggregate.js';
import { rawValues, stats } from '../assets/js/engine/metrics.js';
import { groupKey, project, sideProfile } from '../assets/js/engine/versus.js';

const [inPath, outPath] = process.argv.slice(2);
if (!inPath || !outPath) {
  process.stderr.write('usage: node versus-calibrate.mjs <input.json> <output.json>\n');
  process.exit(2);
}
const input = JSON.parse(readFileSync(inPath, 'utf8'));
const span = input.window ?? 4;
const halfLife = input.halfLife ?? 3;

// A player with no record in the window: no rates, so the engine treats them as average.
// Priors are left out on purpose: they use the whole archive, later seasons included,
// and would leak them into the earlier matches being projected.
const EMPTY = { w: {}, raw: {}, hs: 0 };
for (const c of SUM_COLS) { EMPTY.w[c] = 0; EMPTY.raw[c] = 0; }

const order = [...input.matches].sort((x, y) => (x.scope < y.scope ? -1 : x.scope > y.scope ? 1 : x.year - y.year));
const out = [];
let scope = null, index = null, k = null, aggs = new Map();

for (const m of order) {
  if (!scope || scope.key !== m.scope) {
    scope = JSON.parse(readFileSync(join(input.scopesDir, `${m.scope}.json`), 'utf8'));
    scope.players.priorBat = null; scope.players.priorBowl = null;
    index = new Map(scope.players.id.map((id, pi) => [id, pi]));
    k = input.groups[groupKey(scope)];
    if (!k) throw new Error(`no XI vs XI constants for ${groupKey(scope)} (scope ${m.scope})`);
    // A real eleven's unknown player is a selected cricketer, not a batter forced to bowl:
    // overs no rated bowler covers count as average, so the part-time rate is left out.
    k = { ...k, partTime: undefined };
    aggs = new Map();   // one aggregate per (scope, year); a scope's matches arrive together
  }
  let agg = aggs.get(m.year);
  if (!agg) {
    agg = aggregate(scope, { from: m.year - span, to: m.year - 1, team: null, fullOnly: false, halfLife });
    aggs.set(m.year, agg);
  }
  const side = (ids) => {
    let rated = 0;
    const xi = ids.map((id) => {
      const pi = index.has(id) ? index.get(id) : -1;
      const rec = pi >= 0 ? agg.get(pi) : undefined;
      if (rec) rated++;
      const r = rec ?? EMPTY;
      return { type: null, player: { id, pi, name: pi >= 0 ? scope.players.name[pi] : id, team: -1,
                                     sc: { raw: rawValues(r, scope) }, stats: stats(r) } };
    });
    return { profile: sideProfile(xi, scope, k), rated };
  };
  const A = side(m.a), B = side(m.b);
  const p = project(A.profile, B.profile, k, null);
  if (!Number.isFinite(p.edge)) throw new Error(`non-finite edge for match ${m.id}`);
  out.push({ id: m.id, key: groupKey(scope), edge: p.edge, scoreA: p.scoreA, scoreB: p.scoreB,
             rated: [A.rated, B.rated] });
}
writeFileSync(outPath, JSON.stringify(out));
