// Best XI orchestration: pool -> scores -> exact solve -> order, captain, bench.

import { aggregate } from './aggregate.js';
import { references, roles, scores, stats, utility, SLOT_TYPES, VIRTUAL_SLOTS } from './metrics.js';
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
  const windowAgg = settings.team == null ? all : aggregate(scope, { ...aggOpts, team: settings.team });
  const P = scope.players;
  // Manual choices may use an older observed record, but never replace a record
  // in the selected window or change the recommendation reference population.
  const agg = new Map(windowAgg);
  const older = new Set();
  if (settings.manualPool || settings.locks?.size) {
    const history = aggregate(scope, { ...aggOpts, from: scope.years[0], team: settings.team });
    for (const [pi, rec] of history) {
      if (agg.has(pi) || !(settings.manualPool || settings.locks.has(P.id[pi]))) continue;
      agg.set(pi, rec);
      older.add(pi);
    }
  }
  const types = settings.slots.filter((s) => s.count > 0).map((s) => s.type);
  const concrete = new Set(types.flatMap((t) => VIRTUAL_SLOTS[t] ?? [t]));
  const anyVirtual = types.some((t) => VIRTUAL_SLOTS[t]);
  const pool = [];
  for (const [pi, rec] of agg) {
    const info = { fam: P.fam[pi], wikiKeeper: P.wk ? !!P.wk[pi] : false };
    // A player the user insists on is eligible whatever the evidence bar.
    const locked = !!settings.locks?.has(P.id[pi]);
    const rs = roles(rec, scope, locked || settings.manualPool ? 0 : evidence, info);
    if (!rs.size) continue;
    const sc = scores(rec, scope, ref, pi);
    const util = {}, parts = {}, pick = {};
    const wanted = locked && anyVirtual ? new Set([...concrete, ...VIRTUAL_SLOTS.any]) : concrete;
    for (const t of wanted) {
      if (!rs.has(t)) continue;
      const u = utility(t, sc, settings.weights);
      if (u) { util[t] = u.u; parts[t] = u.parts; }
    }
    const best = (rolesIn) => rolesIn.filter((r) => util[r] != null).sort((a, b) => util[b] - util[a])[0];
    for (const t of types) {
      if (!VIRTUAL_SLOTS[t]) continue;
      // His best role in the slot's group; a locked player outside it takes the slot with his best role overall.
      const r = best(VIRTUAL_SLOTS[t]) ?? (locked ? best(VIRTUAL_SLOTS.any) : undefined);
      if (r) { util[t] = util[r]; parts[t] = parts[r]; pick[t] = r; }
    }
    pool.push({
      id: P.id[pi], pi, name: P.name[pi], team: primaryTeam(rec), roles: rs, sc,
      stats: stats(rec), util, parts, pick, overseas: P.overseas ? !!P.overseas[pi] : false,
      available: available(scope, pi, settings.availability),
      outsideWindow: older.has(pi),
      recordFrom: Math.min(...rec.years), recordTo: Math.max(...rec.years),
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

// Slot types that can stand in for one another when an eleven cannot be shaped
// as asked: an extra all-rounder for a batter, a second spinner for a seamer.
const STAND_IN = {
  opener: ['batter'], batter: ['allrounder', 'finisher', 'opener'], finisher: ['batter', 'allrounder'],
  allrounder: ['batter', 'finisher', 'pace', 'spin'], pace: ['allrounder', 'spin'], spin: ['allrounder', 'pace'],
  keeper: [], bowler: ['allrounder'],
};
const BOWLING = new Set(['allrounder', 'pace', 'spin', 'bowler']);

/**
 * Compositions one or two moves from `slots` that keep a keeper, an opener, a
 * seamer and no fewer than one bowling option below the original.
 */
function nearbyCompositions(slots, usable) {
  const key = (xs) => xs.filter((x) => x.count > 0).map((x) => `${x.type}${x.count}`).sort().join(',');
  const bowlingOf = (xs) => xs.filter((x) => BOWLING.has(x.type)).reduce((a, x) => a + x.count, 0);
  const minBowling = bowlingOf(slots) - 1;
  const count = (xs, t) => xs.find((x) => x.type === t)?.count ?? 0;
  const ok = (xs) => count(xs, 'keeper') === count(slots, 'keeper') &&
    (count(slots, 'opener') === 0 || count(xs, 'opener') >= 1) &&
    (count(slots, 'pace') === 0 || count(xs, 'pace') >= 1) && bowlingOf(xs) >= minBowling;
  const moves = (xs) => {
    const out = [];
    for (const from of xs) {
      if (!from.count) continue;
      for (const to of STAND_IN[from.type] || []) {
        if (!usable.has(to)) continue;
        const next = xs.map((x) => ({ ...x }));
        next.find((x) => x.type === from.type).count--;
        const t = next.find((x) => x.type === to);
        if (t) t.count++; else next.push({ type: to, count: 1 });
        out.push(next);
      }
    }
    return out;
  };
  const seen = new Set([key(slots)]);
  const rings = [];
  let frontier = [slots];
  for (let depth = 0; depth < 2; depth++) {
    const ring = [];
    for (const xs of frontier) {
      for (const n of moves(xs)) {
        const k = key(n);
        if (seen.has(k)) continue;
        seen.add(k);
        ring.push(n);
      }
    }
    rings.push(ring.filter(ok));
    frontier = ring;
  }
  return rings;
}

/**
 * Full selection: XI in batting order, captain, bench, diagnostics. When the
 * evidence bar leaves a slot without enough eligible players, the bar is
 * lowered in steps and the result says so (`relaxed`). If the default shape is
 * still impossible and `settings.flexible` is set, the nearest shape that can
 * be filled is used instead, the best one first, and reported (`reshaped`).
 */
export function selectXI(scope, settings) {
  let relaxed = 1;
  let built, cands, res;
  let slots = settings.slots;
  let reshaped = null;
  const excludes = settings.excludes ?? new Set();
  // A locked player with no scorable record in this scope through the end year
  // is set aside and reported, rather than making every eleven impossible.
  let locks = null, dropped = [];
  const settle = (pool) => {
    if (locks) return;
    const ids = new Set(pool.map((c) => c.id));
    locks = new Set([...(settings.locks ?? [])].filter((id) => ids.has(id)));
    dropped = [...(settings.locks ?? [])].filter((id) => !locks.has(id));
  };
  const constraints = () => ({
    maxOverseas: settings.maxOverseas ?? null, maxPerTeam: settings.maxPerTeam ?? null, locks, excludes,
  });
  const steps = [1, 0.6, 0.35, 0.2];
  for (const step of steps) {
    built = buildPool(scope, { ...settings, evidence: settings.evidence * step });
    settle(built.pool);
    cands = built.pool.filter((c) => c.available || locks.has(c.id));
    res = solve(slots, cands, constraints());
    relaxed = step;
    if (!res.error || settings.strictEvidence) break;
  }
  if (res.error && settings.flexible) {
    search: for (const step of settings.strictEvidence ? [1] : steps) {
      const b = buildPool(scope, { ...settings, slots: Object.keys(STAND_IN).map((type) => ({ type, count: 1 })),
                                   evidence: settings.evidence * step });
      const c = b.pool.filter((x) => x.available || locks.has(x.id));
      const usable = new Set(Object.keys(STAND_IN).filter((t) => c.some((x) => x.util[t] != null)));
      for (const ring of nearbyCompositions(settings.slots, usable)) {
        let best = null;
        for (const xs of ring) {
          const r = solve(xs, c, constraints());
          if (!r.error && (!best || r.total > best.res.total)) best = { xs, res: r };
        }
        if (best) {
          built = b; cands = c; res = best.res; slots = best.xs; reshaped = best.xs; relaxed = step;
          break search;
        }
      }
    }
  }
  if (res.error && (locks?.size || excludes.size) && !settings.slots.some((x) => VIRTUAL_SLOTS[x.type])) {
    // The user's own picks and drops leave no eleven of this shape: keep them all in a free eleven.
    const free = [{ type: 'any', count: 11 }];
    for (const step of settings.strictEvidence ? [1] : steps) {
      const b = buildPool(scope, { ...settings, slots: free, evidence: settings.evidence * step });
      const c = b.pool.filter((x) => x.available || locks.has(x.id));
      const r = solve(free, c, constraints());
      if (!r.error) { built = b; cands = c; res = r; slots = free; reshaped = free; relaxed = step; break; }
    }
  }
  const { pool, ref } = built;
  if (res.error) return { error: res.error, shortfall: shortfall(settings.slots, cands, excludes), pool, ref, droppedLocks: dropped };
  const byId = new Map(pool.map((c) => [c.id, c]));
  // A free slot shows the role the player fills it with; `slot` keeps the slot itself.
  let xi = res.picks.map((p) => {
    const player = byId.get(p.id);
    return { type: player.pick[p.type] ?? p.type, slot: p.type, u: p.u, player, parts: player.parts[p.type] };
  });
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
  for (const s of slots) {
    if (!s.count) continue;
    bench[s.type] = cands.filter((c) => c.util[s.type] != null && !chosen.has(c.id) &&
                                        !(settings.excludes?.has(c.id)))
      .sort((a, b) => b.util[s.type] - a.util[s.type]).slice(0, 5)
      .map((c) => ({ player: c, u: c.util[s.type] }));
  }
  return { xi, total: res.total, optimal: res.optimal, captain, keeper, bench, pool, ref,
           relaxed: relaxed < 1 ? relaxed : null, evidence: built.evidence, slots, reshaped, droppedLocks: dropped };
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
  // Weights are what vary here; a shape found by reshaping stays fixed rather than being searched again.
  const base = settings.flexible ? selectXI(scope, settings) : null;
  if (base?.reshaped) settings = { ...settings, slots: base.slots, flexible: false };
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
