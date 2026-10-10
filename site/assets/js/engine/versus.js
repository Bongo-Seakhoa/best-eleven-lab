// XI vs XI: two elevens as runs per innings, and the match they project.
//
// Every player's value is the model's adjusted runs per ball: runs added per ball
// faced, runs saved per ball bowled, against an average player and pulled towards
// his prior for short records (metrics.rawValues). A side may be picked in one
// format and play in another: each player is then rated in the match format, from
// his own record there over the side's years, or from his prior there alone (what
// his record elsewhere predicts, model/priors.py). Turning rates into runs per
// innings uses facts about real innings in the match format (model/versus.json):
// innings length, the share each batting position faces, innings per side, par,
// and the rate occasional bowlers concede.

import { aggregate } from './aggregate.js';
import { rawValues, priorOf } from './metrics.js';

const BANDS = [['top', 'Top order', 0, 3], ['middle', 'Middle order', 3, 7], ['lower', 'Lower order', 7, 11]];
const TEST_SHARE_CAP = 0.35;    // no quota in Tests; no one bowls much more than a third of an innings
const WORKLOAD_STRETCH = 1.25;  // a bowler may do up to a quarter more than his usual share
const REGULAR = 0.05;           // a usual share below this makes a player an occasional bowler

/** Key into versus.json groups for a scope. */
export const groupKey = (scope) => `${scope.tier}:${scope.gender}:${scope.family}`;

/** True when two scopes' ratings come from one fit (one scale) and share a match format. */
export const comparable = (a, b) => a.family === b.family && a.gender === b.gender && a.tier === b.tier &&
  (a.fitGroup ?? null) === (b.fitGroup ?? null);

/** Rates of an eleven in its own selection format (the engine's window ratings). */
export function ownRates(xi, scope, k) {
  const perInnings = k.innings > 0 ? k.innings : 1;
  return xi.map((x) => {
    const raw = x.player.sc.raw, prior = priorOf(scope, x.player.pi);
    const bowls = raw.bowlRate != null && (x.player.stats.ballsPerMatchBowled || 0) > 0;
    return {
      batRate: raw.batRate ?? prior.bat,
      bowlRate: bowls ? raw.bowlRate : null,
      usual: bowls ? (x.player.stats.ballsPerMatchBowled / perInnings) / k.balls : 0,
      fam: scope.players.fam?.[x.player.pi] || '',
      from: 'record',
    };
  });
}

/**
 * The match scope filtered as its own Best XI would be for this side: the
 * side's years, its team if that team plays the format, and the Full-Member rule
 * for a World XI. One player then has one rating per format, whichever side he is in.
 */
export function matchFilters(matchScope, st) {
  const idx = st.team && matchScope.tier === 'national' ? matchScope.teams.indexOf(st.team) : -1;
  const team = idx >= 0 ? idx : null;
  return { team, fullOnly: matchScope.tier === 'national' && !!st.fo && team === null };
}

/** The match scope over a side's years. */
export function matchAggregate(matchScope, st) {
  return aggregate(matchScope, { from: st.from, to: st.to, ...matchFilters(matchScope, st), halfLife: st.hl || 0 });
}

/** Every player's whole record in the match scope, up to the side's last year (nothing later). */
export function matchCareer(matchScope, st) {
  return aggregate(matchScope, { from: matchScope.years[0], to: st.to, ...matchFilters(matchScope, st), halfLife: 0 });
}

/**
 * A player's own records in the match format, batting and bowling each on its
 * own: over his side's years if he did it then, otherwise over his whole record
 * up to then, otherwise none.
 */
export function matchRecord(id, match) {
  const none = { rec: null, where: null };
  const pi = match.index.get(id);
  if (pi == null) return { pi: null, bat: none, bowl: none };
  const inYears = match.agg.get(pi), career = match.career?.get(pi);
  const pick = (did) => (inYears && did(inYears) ? { rec: inYears, where: 'years' }
    : career && did(career) ? { rec: career, where: 'career' } : none);
  return { pi, bat: pick((r) => r.raw.b > 0), bowl: pick((r) => r.raw.wb > 0) };
}

const priorIndex = new WeakMap();   // priors doc -> unit -> Map(id -> row)
function listedIndex(priors, unit) {
  if (!priors?.players?.[unit]) return new Map();
  let units = priorIndex.get(priors);
  if (!units) { units = new Map(); priorIndex.set(priors, units); }
  if (!units.has(unit)) units.set(unit, new Map(priors.players[unit].id.map((id, i) => [id, i])));
  return units.get(unit);
}

/**
 * Rates of an eleven picked in `side.scope` when the match is played in
 * `match.scope`. Each player's own records in the match format come first (the
 * same ratings the rest of the site shows for him there); only a discipline he
 * never did in that format is rated on what his other cricket predicts
 * (`match.priors`, model/priors.json).
 */
export function crossRates(xi, side, match) {
  const unit = match.scope.key;
  const base = match.priors?.targets?.[unit];
  const listed = match.priors?.players?.[unit];
  const elsewhere = listedIndex(match.priors, unit);
  const perMatch = match.k.innings > 0 ? match.k.innings : 1;
  const sidePerMatch = side.k.innings > 0 ? side.k.innings : 1;
  return xi.map((x) => {
    const id = x.player.id;
    const { pi, bat, bowl } = matchRecord(id, match);
    let prior;
    if (pi != null) prior = priorOf(match.scope, pi);
    else if (elsewhere.has(id)) prior = { bat: listed.bat[elsewhere.get(id)], bowl: listed.bowl[elsewhere.get(id)] };
    else prior = { bat: base?.bat?.baseline ?? 0, bowl: base?.bowl?.baseline ?? 0 };
    const batRaw = bat.rec ? rawValues(bat.rec, match.scope, pi, prior) : null;
    const bowlRaw = bowl.rec ? (bowl.rec === bat.rec ? batRaw : rawValues(bowl.rec, match.scope, pi, prior)) : null;
    const ownBowls = (x.player.stats.ballsPerMatchBowled || 0) > 0;
    const usual = bowl.rec && bowl.rec.raw.m > 0 ? (bowl.rec.raw.wb / bowl.rec.raw.m / perMatch) / match.k.balls
      : ownBowls ? (x.player.stats.ballsPerMatchBowled / sidePerMatch) / side.k.balls : 0;
    const wheres = [bat.where, bowl.where];
    return {
      batRate: batRaw?.batRate ?? prior.bat,
      bowlRate: bowlRaw ? bowlRaw.bowlRate : ownBowls ? prior.bowl : null,
      usual,
      fam: side.scope.players.fam?.[x.player.pi] || '',
      from: !bat.where && !bowl.where ? 'prior' : wheres.includes('career') ? 'career' : 'record',
      bat: bat.where, bowl: bowl.where,
    };
  });
}

/**
 * Who bowls how much, as shares of an innings.
 *   1. The best bowlers first, each up to the quota and at most a quarter beyond
 *      his usual workload.
 *   2. If overs remain, the heaviest-worked regular bowlers take more, up to the
 *      quota, as a captain leans on his frontline attack.
 *   3. If overs still remain (an eleven short of bowlers), anyone takes them up to
 *      the quota, and an occasional bowler pays no better than the rate real
 *      part-timers concede (`partTime`): his own short record comes from spells
 *      chosen to suit him, not from bowling a full share.
 * @returns {{shares: number[], rates: number[], partTime: number}}
 */
export function bowlingShares(rates, k) {
  const cap = k.quota ?? TEST_SHARE_CAP;
  const part = Number.isFinite(k.partTime) ? k.partTime : 0;
  const n = rates.length;
  const share = new Array(n).fill(0), runs = new Array(n).fill(0);
  let left = 1, forced = 0;
  const give = (i, upto, rate) => {
    const add = Math.min(Math.max(0, upto - share[i]), left);
    if (add <= 0) return 0;
    share[i] += add; runs[i] += add * rate; left -= add;
    return add;
  };
  const bowlers = rates.map((r, i) => ({ i, ...r })).filter((r) => r.bowlRate != null && r.usual > 0);
  for (const b of [...bowlers].sort((a, b2) => b2.bowlRate - a.bowlRate)) {
    if (left <= 1e-9) break;
    give(b.i, Math.min(cap, WORKLOAD_STRETCH * b.usual), b.bowlRate);
  }
  for (const b of [...bowlers].filter((r) => r.usual >= REGULAR).sort((a, b2) => b2.usual - a.usual)) {
    if (left <= 1e-9) break;
    give(b.i, cap, b.bowlRate);
  }
  if (left > 1e-9) {
    const effective = (r) => (r.bowlRate != null && r.usual >= REGULAR ? r.bowlRate : Math.min(r.bowlRate ?? part, part));
    const all = rates.map((r, i) => ({ i, rate: effective(r) })).sort((a, b2) => b2.rate - a.rate);
    for (const r of all) {
      if (left <= 1e-9) break;
      forced += give(r.i, cap, r.rate);
    }
  }
  return { shares: share, runs, forced, unfilled: Math.max(0, left) };
}

/**
 * One side per innings. `xi` is the eleven in batting order ([{type, player}]);
 * `rates` (from ownRates or crossRates) defaults to the eleven's own ratings.
 * Returns runs added batting and runs saved bowling against an average side.
 */
export function sideProfile(xi, scope, k, rates = ownRates(xi, scope, k)) {
  const bowling = bowlingShares(rates, k);
  const players = xi.map((x, i) => {
    const r = rates[i];
    const batShare = k.share[i] ?? 0;
    return {
      id: x.player.id, name: x.player.name, type: x.type, pos: i + 1, team: x.player.team, pi: x.player.pi,
      batRate: r.batRate, bowlRate: r.bowlRate, batShare, from: r.from,
      bat: batShare * k.balls * (r.batRate ?? 0),
      bowlShare: bowling.shares[i], bowl: bowling.runs[i] * k.balls,
      fam: r.fam,
    };
  });
  const sum = (xs, f) => xs.reduce((a, x) => a + f(x), 0);
  const bands = BANDS.map(([key, label, a, b]) => ({ key, label, runs: sum(players.slice(a, b), (p) => p.bat) }));
  const attack = ['pace', 'spin'].map((fam) => {
    const ps = players.filter((p) => p.fam === fam && p.bowlShare > 0);
    return { fam, share: sum(ps, (p) => p.bowlShare), runs: sum(ps, (p) => p.bowl) };
  });
  const other = players.filter((p) => p.bowlShare > 0 && p.fam !== 'pace' && p.fam !== 'spin');
  if (other.length) attack.push({ fam: 'unknown', share: sum(other, (p) => p.bowlShare), runs: sum(other, (p) => p.bowl) });
  return { players, bat: sum(players, (p) => p.bat), bowl: sum(players, (p) => p.bowl), bands, attack,
           forced: bowling.forced, unfilled: bowling.unfilled };
}

/** Win chances from a calibrated edge; null when the build carries no calibration. */
export function chances(edge, cal) {
  if (!cal || !Number.isFinite(cal.k)) return null;
  const s = (x) => 1 / (1 + Math.exp(-x));
  if (Number.isFinite(cal.c) && cal.c > 0) {       // Tests: an ordered model with a draw band
    const a = s(cal.k * edge - cal.c), b = s(-cal.k * edge - cal.c);
    return { a, b, draw: Math.max(0, 1 - a - b) };
  }
  const a = s(cal.k * edge);
  return { a, b: 1 - a, draw: 0 };
}

/**
 * The projected match between two profiled sides on an average pitch at a
 * neutral venue. Scores are per innings; `edge` is runs per match, positive
 * when side A is stronger.
 */
export function project(A, B, k, cal) {
  const scoreA = k.par + A.bat - B.bowl;
  const scoreB = k.par + B.bat - A.bowl;
  const edge = k.innings * (scoreA - scoreB);
  return {
    scoreA, scoreB, edge,
    parts: {
      batting: k.innings * (A.bat - B.bat),
      bowling: k.innings * (A.bowl - B.bowl),
    },
    chances: chances(edge, cal),
  };
}
