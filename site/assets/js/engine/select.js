// Best XI orchestration: pool -> scores -> exact solve -> order, captain, bench.

import { aggregate } from './aggregate.js';
import { references, roles, scores, stats, utility, SLOT_TYPES } from './metrics.js';
import { solve } from './solver.js';

export const DEFAULT_WEIGHTS = { quality: 80, legacy: 0, experience: 12, leadership: 8 };

export const PRESETS = {
  balanced:   { label: 'Balanced',         weights: { quality: 80, legacy: 0, experience: 12, leadership: 8 }, halfLife: 3 },
  quality:    { label: 'Pure output',      weights: { quality: 100, legacy: 0, experience: 0, leadership: 0 }, halfLife: 0 },
  form:       { label: 'Current form',     weights: { quality: 85, legacy: 0, experience: 10, leadership: 5 }, halfLife: 1 },
  alltime:    { label: 'All-time greats',  weights: { quality: 55, legacy: 35, experience: 10, leadership: 0 }, halfLife: 0 },
  legacy:     { label: 'Legacy',           weights: { quality: 30, legacy: 60, experience: 10, leadership: 0 }, halfLife: 0 },
  experience: { label: 'Big-match nous',   weights: { quality: 50, legacy: 0, experience: 30, leadership: 20 }, halfLife: 3 },
};

export const TEMPLATES = {
  multi:   [['opener', 2], ['batter', 3], ['keeper', 1], ['allrounder', 1], ['pace', 3], ['spin', 1]],
  fifty:   [['opener', 2], ['batter', 3], ['keeper', 1], ['allrounder', 2], ['pace', 2], ['spin', 1]],
  t20:     [['opener', 2], ['batter', 2], ['finisher', 1], ['keeper', 1], ['allrounder', 2], ['pace', 2], ['spin', 1]],
  hundred: [['opener', 2], ['batter', 2], ['finisher', 1], ['keeper', 1], ['allrounder', 2], ['pace', 2], ['spin', 1]],
};

export function defaultSlots(family) {
  return TEMPLATES[family].map(([type, count]) => ({ type, count }));
}

function primaryTeam(rec) {
  let best = null, n = -1;
  for (const [t, m] of rec.teams) if (m > n) { best = t; n = m; }
  return best;
}

/** Availability test against the player database flags in scope.players. */
export function available(scope, pi, mode) {
  const P = scope.players;
  if (mode === 'any') return true;
  if (mode === 'squad') return !!(P.squad && P.squad[pi]);
  return !!(P.active && P.active[pi]);
}

/**
 * Evidence thresholds are sized for a six-year window; shorter windows ask for
 * proportionally fewer balls, longer ones for more (bounded both ways).
 */
export function windowFactor(from, to) {
  return Math.min(2, Math.max(0.35, (to - from + 1) / 6));
}

/**
 * Build the scored candidate pool for a scope and settings.
 * settings: {from, to, team, fullOnly, halfLife, evidence, availability, weights, slots}
 */
export function buildPool(scope, settings) {
  const aggOpts = { from: settings.from, to: settings.to, fullOnly: settings.fullOnly,
                    halfLife: settings.halfLife };
  const evidence = settings.evidence * windowFactor(settings.from, settings.to);
  const all = aggregate(scope, { ...aggOpts, team: null });
  const ref = references(all, scope, evidence);
  const agg = settings.team == null ? all : aggregate(scope, { ...aggOpts, team: settings.team });
  const P = scope.players;
  const types = settings.slots.filter((s) => s.count > 0).map((s) => s.type);
  const pool = [];
  for (const [pi, rec] of agg) {
    const info = { fam: P.fam[pi], wikiKeeper: P.wk ? !!P.wk[pi] : false };
    const rs = roles(rec, scope, evidence, info);
    if (!rs.size) continue;
    const sc = scores(rec, scope, ref, pi);
    const util = {}, parts = {};
    for (const t of types) {
      if (!rs.has(t)) continue;
      const u = utility(t, sc, settings.weights);
      if (u) { util[t] = u.u; parts[t] = u.parts; }
    }
    pool.push({
      id: P.id[pi], pi, name: P.name[pi], team: primaryTeam(rec), roles: rs, sc,
      stats: stats(rec), util, parts, overseas: P.overseas ? !!P.overseas[pi] : false,
      available: available(scope, pi, settings.availability),
    });
  }
  return { pool, ref, agg, evidence };
}

export function battingOrder(xi) {
  const rank = { opener: 0, batter: 1, keeper: 2, finisher: 2, allrounder: 3, pace: 4, spin: 4, bowler: 4 };
  return xi.slice().sort((a, b) => {
    const ra = rank[a.type], rb = rank[b.type];
    if (ra !== rb && (ra === 0 || rb === 0 || ra === 4 || rb === 4)) return ra - rb;
    const pa = a.player.stats.posAvg ?? 9, pb = b.player.stats.posAvg ?? 9;
    if (ra === 4) return (b.player.sc.batQ ?? 0) - (a.player.sc.batQ ?? 0);
    return pa - pb;
  });
}

function shortfall(slots, cands, excludes) {
  return slots.filter((s) => s.count > 0).map((s) => ({
    type: s.type, need: s.count,
    have: cands.filter((c) => c.util[s.type] != null && !excludes.has(c.id)).length,
  }));
}

/**
 * Full selection: XI in batting order, captain, bench, diagnostics. When the
 * evidence bar leaves a slot without enough eligible players, the bar is
 * lowered in steps and the result says so (`relaxed`).
 */
export function selectXI(scope, settings) {
  let relaxed = 1;
  let built, cands, res;
  const excludes = settings.excludes ?? new Set();
  for (const step of [1, 0.6, 0.35, 0.2]) {
    built = buildPool(scope, { ...settings, evidence: settings.evidence * step });
    cands = built.pool.filter((c) => c.available || settings.locks?.has(c.id));
    res = solve(settings.slots, cands, {
      maxOverseas: settings.maxOverseas ?? null, maxPerTeam: settings.maxPerTeam ?? null,
      locks: settings.locks ?? new Set(), excludes,
    });
    relaxed = step;
    if (!res.error || settings.strictEvidence) break;
  }
  const { pool, ref } = built;
  if (res.error) return { error: res.error, shortfall: shortfall(settings.slots, cands, excludes), pool, ref };
  const byId = new Map(pool.map((c) => [c.id, c]));
  let xi = res.picks.map((p) => ({ type: p.type, u: p.u, player: byId.get(p.id),
                                   parts: byId.get(p.id).parts[p.type] }));
  xi = battingOrder(xi);
  let captain = null;
  // A current captain (squad page marker) leads when selected; otherwise the
  // most-capped captain in the eleven.
  const current = scope.players.cc ? xi.filter((x) => scope.players.cc[x.player.pi]) : [];
  if (current.length && settings.availability !== 'any') {
    captain = current.reduce((a, b) => ((b.player.sc.captMatches || 0) > (a.player.sc.captMatches || 0) ? b : a)).player.id;
  }
  else if (scope.players.capt) {
    const withC = xi.filter((x) => (x.player.sc.captMatches || 0) > 0);
    if (withC.length) captain = withC.reduce((a, b) => (b.player.sc.captMatches > a.player.sc.captMatches ? b : a)).player.id;
  }
  // Gloves go to whoever in the eleven keeps most often; the solved slots stand.
  const share = (x) => (x.player.stats.matches ? x.player.stats.kept / x.player.stats.matches : 0);
  const keepers = xi.filter((x) => x.player.roles.has('keeper'));
  const keeper = keepers.length ? keepers.reduce((a, b) => (share(b) > share(a) ? b : a)).player.id : null;
  const chosen = new Set(xi.map((x) => x.player.id));
  const bench = {};
  for (const s of settings.slots) {
    if (!s.count) continue;
    bench[s.type] = cands.filter((c) => c.util[s.type] != null && !chosen.has(c.id) &&
                                        !(settings.excludes?.has(c.id)))
      .sort((a, b) => b.util[s.type] - a.util[s.type]).slice(0, 5)
      .map((c) => ({ player: c, u: c.util[s.type] }));
  }
  return { xi, total: res.total, optimal: res.optimal, captain, keeper, bench, pool, ref,
           relaxed: relaxed < 1 ? relaxed : null, evidence: built.evidence };
}

/** What the team loses (in utility) if `id` must be included. */
export function whyNot(scope, settings, id, base) {
  const locks = new Set(settings.locks ?? []); locks.add(id);
  const excludes = new Set(settings.excludes ?? []); excludes.delete(id);
  const alt = selectXI(scope, { ...settings, locks, excludes });
  if (alt.error) return { error: alt.error };
  const dropped = base.xi.filter((x) => !alt.xi.some((y) => y.player.id === x.player.id));
  return { delta: alt.total - base.total, dropped, alt };
}

/** Selection frequency under random +-25% perturbations of the weights. */
export function stability(scope, settings, runs = 24) {
  let seed = 7;
  const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  const counts = new Map();
  for (let r = 0; r < runs; r++) {
    const w = {};
    for (const [k, v] of Object.entries(settings.weights)) w[k] = v * (0.75 + 0.5 * rnd());
    const res = selectXI(scope, { ...settings, weights: w });
    if (res.error) continue;
    for (const x of res.xi) counts.set(x.player.id, (counts.get(x.player.id) || 0) + 1);
  }
  return new Map([...counts].map(([k, v]) => [k, v / runs]));
}

export { SLOT_TYPES };
