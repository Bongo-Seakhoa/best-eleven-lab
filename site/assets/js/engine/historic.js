// All-eras selection from career records (Wikipedia national lists).
//
// Career totals carry no batting positions or ball counts, so quality is
// era-relative: a batting average against the average of the decade the career
// was centred on, a bowling average likewise, each shrunk toward that average
// for short careers. Legacy is runs (or wickets) above the era average.

import { solve } from './solver.js';

export const HISTORIC_TEMPLATE = [
  { type: 'batter', count: 5 }, { type: 'keeper', count: 1 }, { type: 'allrounder', count: 1 },
  { type: 'pace', count: 3 }, { type: 'spin', count: 1 },
];
const RULES = {
  Test: { minOuts: 15, minWkts: 30, wktsPerMatch: 1.2, arWktsPerMatch: 1.0, arAvgIndex: 0.8, kBat: 8, kBowl: 10 },
  ODI:  { minOuts: 12, minWkts: 30, wktsPerMatch: 0.8, arWktsPerMatch: 0.6, arAvgIndex: 0.8, kBat: 8, kBowl: 12 },
};

function meanSd(xs) {
  const v = xs.filter((x) => Number.isFinite(x));
  if (v.length < 2) return { mean: 0, sd: 1 };
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  return { mean, sd: Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (v.length - 1)) || 1 };
}
const scale = (x, r) => (x == null || !Number.isFinite(x) ? null : Math.max(0, Math.min(100, 50 + 15 * (x - r.mean) / r.sd)));

/** One record per person: World XIs merge players who represented two countries. */
function records(H, country, fullOnly = false) {
  const P = H.players, n = P.name.length, byKey = new Map();
  const full = new Set(H.fullMembers || []);
  for (let i = 0; i < n; i++) {
    if (country && P.country[i] !== country) continue;
    if (!country && fullOnly && !full.has(P.country[i])) continue;
    const key = P.title[i] || `${P.name[i]}|${P.country[i]}`;
    let r = byKey.get(key);
    if (!r) {
      r = { key, idx: i, name: P.name[i], title: P.title[i], id: P.id[i], countries: [], first: P.first[i], last: P.last[i],
            m: 0, runs: 0, outs: 0, wkts: 0, rc: 0, ct: 0, st: 0, h100: 0, capt: 0, captMark: 0, keepMark: 0,
            batBase: 0, bowlBase: 0, hand: P.hand[i], bowl: P.bowl[i], fam: P.fam[i], role: P.role[i] };
      byKey.set(key, r);
    }
    const base = H.baselines[String(P.decade[i])] || { bat: 30, bowl: 30 };
    r.countries.push(P.country[i]);
    r.first = Math.min(r.first, P.first[i]); r.last = Math.max(r.last, P.last[i]);
    for (const c of ['m', 'runs', 'outs', 'wkts', 'rc', 'ct', 'st', 'capt']) r[c] += P[c][i];
    r.h100 += Math.max(0, P.h100[i]);
    r.captMark |= P.captMark[i]; r.keepMark |= P.keepMark[i];
    r.batBase += P.outs[i] * base.bat;          // dismissal-weighted era average
    r.bowlBase += P.wkts[i] * base.bowl;        // wicket-weighted era average
    r._decBat = base.bat; r._decBowl = base.bowl;
  }
  for (const r of byKey.values()) {
    r.eraBat = r.outs > 0 ? r.batBase / r.outs : r._decBat;
    r.eraBowl = r.wkts > 0 ? r.bowlBase / r.wkts : r._decBowl;
  }
  return [...byKey.values()];
}

export function historicPool(H, settings) {
  const rule = RULES[H.format];
  // Reference scale always uses Full Members, so a country's XI and the World XI share one scale.
  const all = records(H, null, true);
  const pool = settings.country ? records(H, settings.country) : records(H, null, settings.fullOnly !== false);
  const raw = (r) => {
    const avg = r.outs > 0 ? r.runs / r.outs : null;
    const bowlAvg = r.wkts > 0 ? r.rc / r.wkts : null;
    const batIndex = (r.runs + rule.kBat * r.eraBat) / (r.outs + rule.kBat) / r.eraBat;
    const bowlIndex = r.wkts > 0 ? r.eraBowl / ((r.rc + rule.kBowl * r.eraBowl) / (r.wkts + rule.kBowl)) : null;
    return { avg, bowlAvg, batIndex, bowlIndex, batL: r.runs - r.outs * r.eraBat,
             bowlL: r.wkts > 0 ? r.wkts * r.eraBowl - r.rc : null };
  };
  const qualBat = (r) => r.outs >= rule.minOuts;
  const qualBowl = (r) => r.wkts >= rule.minWkts && r.wkts / Math.max(r.m, 1) >= rule.wktsPerMatch;
  const refRows = all.map((r) => ({ r, v: raw(r) }));
  const ref = {
    batQ: meanSd(refRows.filter(({ r }) => qualBat(r)).map(({ v }) => v.batIndex)),
    bowlQ: meanSd(refRows.filter(({ r }) => qualBowl(r)).map(({ v }) => v.bowlIndex)),
    batL: meanSd(refRows.filter(({ r }) => qualBat(r)).map(({ v }) => v.batL)),
    bowlL: meanSd(refRows.filter(({ r }) => qualBowl(r)).map(({ v }) => v.bowlL)),
    maxM: Math.max(...all.map((r) => r.m), 1), maxC: Math.max(...all.map((r) => r.capt), 1),
  };
  const w = settings.weights;
  const out = [];
  for (const r of pool) {
    const v = raw(r);
    const roles = new Set();
    const bat = qualBat(r), bowl = qualBowl(r);
    const keeper = r.st > 0 && (r.keepMark || /wicket-keeper/.test(r.role) || r.st >= 3) && r.outs >= rule.minOuts * 0.6;
    if (bat) roles.add('batter');
    if (keeper) roles.add('keeper');
    if (bowl && r.fam === 'pace') roles.add('pace');
    if (bowl && r.fam === 'spin') roles.add('spin');
    if (bowl) roles.add('bowler');
    if (bat && v.batIndex >= rule.arAvgIndex && r.wkts >= rule.minWkts &&
        r.wkts / Math.max(r.m, 1) >= rule.arWktsPerMatch) roles.add('allrounder');
    if (!roles.size) continue;
    const sc = {
      batQ: scale(v.batIndex, ref.batQ), bowlQ: scale(v.bowlIndex, ref.bowlQ),
      batL: scale(v.batL, ref.batL), bowlL: scale(v.bowlL, ref.bowlL),
      exp: 100 * Math.log1p(r.m) / Math.log1p(ref.maxM),
      lead: 100 * Math.log1p(r.capt + (r.captMark && !r.capt ? 5 : 0)) / Math.log1p(ref.maxC),
    };
    const util = {};
    for (const t of roles) {
      const q = t === 'allrounder' ? (sc.batQ + (sc.bowlQ ?? 0)) / 2
        : ['batter', 'keeper'].includes(t) ? sc.batQ : sc.bowlQ;
      const l = t === 'allrounder' ? ((sc.batL ?? 0) + (sc.bowlL ?? 0)) / 2
        : ['batter', 'keeper'].includes(t) ? sc.batL : sc.bowlL;
      if (q == null) continue;
      const tot = w.quality + w.legacy + w.experience + w.leadership;
      util[t] = (w.quality * q + w.legacy * (l ?? 0) + w.experience * sc.exp + w.leadership * sc.lead) / (tot || 1);
    }
    out.push({ id: r.key, rec: r, name: r.name, team: r.countries[0], roles, sc, util,
               stats: { matches: r.m, runs: r.runs, avg: v.avg, wkts: r.wkts, bowlAvg: v.bowlAvg,
                        eraBat: r.eraBat, eraBowl: r.eraBowl, batIndex: v.batIndex, bowlIndex: v.bowlIndex,
                        hundreds: r.h100, catches: r.ct, stumpings: r.st, span: `${r.first}-${r.last}` } });
  }
  return { pool: out, ref };
}

export function selectHistoric(H, settings) {
  const { pool, ref } = historicPool(H, settings);
  const slots = settings.slots ?? HISTORIC_TEMPLATE;
  const res = solve(slots, pool, { maxPerTeam: settings.country ? null : settings.maxPerTeam ?? null,
                                   locks: settings.locks ?? new Set(), excludes: settings.excludes ?? new Set() });
  if (res.error) return { error: res.error, pool };
  const byId = new Map(pool.map((c) => [c.id, c]));
  const order = { batter: 0, keeper: 1, allrounder: 2, pace: 3, spin: 3, bowler: 3 };
  const xi = res.picks.map((p) => ({ type: p.type, u: p.u, player: byId.get(p.id) }))
    .sort((a, b) => order[a.type] - order[b.type] ||
      (order[a.type] === 3 ? (b.player.sc.batQ ?? 0) - (a.player.sc.batQ ?? 0)
                           : (b.player.sc.batQ ?? 0) - (a.player.sc.batQ ?? 0)));
  const capt = xi.filter((x) => x.player.rec.capt > 0 || x.player.rec.captMark);
  const captain = capt.length ? capt.reduce((a, b) => (b.player.rec.capt > a.player.rec.capt ? b : a)).player.id : null;
  return { xi, total: res.total, captain, keeper: xi.find((x) => x.type === 'keeper')?.player.id ?? null, pool, ref };
}
