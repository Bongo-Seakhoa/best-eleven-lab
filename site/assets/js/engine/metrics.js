// Derived statistics, role eligibility and 0-100 component scores.

export const FAMILY_RULES = {
  multi:   { minBat: 500, minBowl: 900, arBowlPerMatch: 30, label: 'per innings' },
  fifty:   { minBat: 300, minBowl: 450, arBowlPerMatch: 18, label: 'per 100 balls' },
  t20:     { minBat: 150, minBowl: 180, arBowlPerMatch: 9,  label: 'per 100 balls' },
  hundred: { minBat: 120, minBowl: 150, arBowlPerMatch: 8,  label: 'per 100 balls' },
};

export const SLOT_TYPES = {
  opener:     { label: 'Opener',          short: 'OPN' },
  batter:     { label: 'Top-order batter', short: 'BAT' },
  finisher:   { label: 'Finisher',        short: 'FIN' },
  keeper:     { label: 'Wicketkeeper',    short: 'WK' },
  allrounder: { label: 'All-rounder',     short: 'AR' },
  pace:       { label: 'Pace bowler',     short: 'PACE' },
  spin:       { label: 'Spin bowler',     short: 'SPIN' },
  bowler:     { label: 'Bowler',          short: 'BWL' },
  // Free slots for XI vs XI: any player, a batting pick, a bowling pick.
  any:        { label: 'Free pick',       short: 'ANY', virtual: true },
  bat:        { label: 'Batting pick',    short: 'BAT', virtual: true },
  bowl:       { label: 'Bowling pick',    short: 'BWL', virtual: true },
};

/** The roles each free slot draws on; a player fills it with his best one. */
export const VIRTUAL_SLOTS = {
  any: ['opener', 'batter', 'finisher', 'keeper', 'allrounder', 'pace', 'spin', 'bowler'],
  bat: ['opener', 'batter', 'finisher', 'keeper', 'allrounder'],
  bowl: ['allrounder', 'pace', 'spin', 'bowler'],
};

const div = (a, b) => (b > 0 ? a / b : null);

export function stats(rec) {
  const r = rec.raw;
  return {
    matches: r.m,
    inns: r.bi,
    runs: r.r,
    avg: div(r.r, r.out),
    sr: div(100 * r.r, r.b),
    hundreds: r.h100,
    fifties: r.h50,
    hs: rec.hs,
    boundaryPct: div(100 * (4 * r.f4 + 6 * r.f6), r.r),
    dotPct: div(100 * r.d0, r.b),
    wkts: r.ww,
    bowlAvg: div(r.wr, r.ww),
    econ: div(6 * r.wr, r.wb),
    bowlSr: div(r.wb, r.ww),
    fiveW: r.w5,
    catches: r.ct + r.kc,
    stumpings: r.st,
    kept: r.kp,
    posAvg: div(1.5 * r.p12 + 3 * r.p3 + 5 * r.p46 + 8.5 * r.p7, r.bi),
    ballsPerMatchBowled: div(r.wb, r.m),
    deathShare: div(r.wp2, r.wp0 + r.wp1 + r.wp2),
  };
}

/**
 * A player's prior in runs per ball: what his record elsewhere predicts here
 * (scope.players.priorBat / priorBowl, model/priors.py), or zero, an average
 * Full-Member player, where a scope has no priors.
 */
export function priorOf(scope, pi) {
  const P = scope.players;
  return { bat: (pi != null && P.priorBat?.[pi]) || 0, bowl: (pi != null && P.priorBowl?.[pi]) || 0 };
}

/** Raw (unscaled) quality and legacy values for one aggregated player. */
export function rawValues(rec, scope, pi = null, prior = priorOf(scope, pi)) {
  const { w, raw } = rec;
  const lb = scope.lambda.bat, lw = scope.lambda.bowl;
  // A short record is pulled towards the prior, a long one barely moves.
  const batRate = w.b > 0 ? (w.ba + lb * prior.bat) / (w.b + lb) : null;      // runs added per ball
  const bowlRate = w.wb > 0 ? (-w.wc + lw * prior.bowl) / (w.wb + lw) : null; // runs saved per ball
  const perInnings = scope.family === 'multi';
  const ballsPerInn = raw.bi > 0 ? raw.b / raw.bi : 0;
  return {
    batQ: batRate === null ? null : perInnings ? batRate * ballsPerInn : batRate * 100,
    bowlQ: bowlRate === null ? null : bowlRate * 100,
    batL: w.b > 0 ? w.ba : null,
    bowlL: w.wb > 0 ? -w.wc : null,
    keepRate: raw.kp > 0 ? (raw.kc + raw.st) / raw.kp : null,
    batRate, bowlRate,
  };
}

export function roles(rec, scope, evidence = 1, info = {}) {
  const rule = FAMILY_RULES[scope.family];
  const r = rec.raw;
  const minBat = rule.minBat * evidence, minBowl = rule.minBowl * evidence;
  const batQ = r.b >= minBat;
  const bowlQ = r.wb >= minBowl;
  const bi = Math.max(r.bi, 1);
  const top6 = (r.p12 + r.p3 + r.p46) / bi;
  const out = new Set();
  if (batQ && r.p12 / bi >= 0.5) out.add('opener');
  if (batQ && top6 >= 0.6) out.add('batter');
  if (batQ && scope.family !== 'multi' && (r.p46 + r.p7) / bi >= 0.6) out.add('finisher');
  const keptShare = r.m > 0 ? r.kp / r.m : 0;
  if (r.b >= minBat * 0.5 && (keptShare >= 0.3 || (info.wikiKeeper && r.kp > 0))) out.add('keeper');
  const posAvg = (1.5 * r.p12 + 3 * r.p3 + 5 * r.p46 + 8.5 * r.p7) / bi;
  if (r.b >= minBat * 0.6 && posAvg <= 7.5 && r.wb >= minBowl * 0.6 &&
      r.m > 0 && r.wb / r.m >= rule.arBowlPerMatch) out.add('allrounder');
  if (bowlQ) {
    out.add('bowler');
    if (info.fam === 'pace') out.add('pace');
    if (info.fam === 'spin') out.add('spin');
  }
  return out;
}

function meanSd(xs) {
  const v = xs.filter((x) => x !== null && Number.isFinite(x));
  if (v.length < 2) return { mean: 0, sd: 1, n: v.length };
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  const sd = Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (v.length - 1)) || 1;
  return { mean, sd, n: v.length };
}

const scale = (x, ref) => (x === null ? null : Math.max(0, Math.min(100, 50 + 15 * (x - ref.mean) / ref.sd)));

/**
 * Reference distributions for the scope + window, from qualified players of
 * every team, so team and World XIs share one scale.
 */
export function references(agg, scope, evidence = 1) {
  let memo = refCache.get(agg);
  if (!memo) { memo = new Map(); refCache.set(agg, memo); }
  if (!memo.has(evidence)) memo.set(evidence, computeReferences(agg, scope, evidence));
  return memo.get(evidence);
}
const refCache = new WeakMap();

function computeReferences(agg, scope, evidence) {
  const rule = FAMILY_RULES[scope.family];
  const bat = [], bowl = [], batL = [], bowlL = [], keep = [];
  let maxExp = 1, maxCapt = 1;
  for (const [pi, rec] of agg) {
    const v = rawValues(rec, scope, pi);
    if (rec.raw.b >= rule.minBat * evidence) { bat.push(v.batQ); batL.push(v.batL); }
    if (rec.raw.wb >= rule.minBowl * evidence) { bowl.push(v.bowlQ); bowlL.push(v.bowlL); }
    if (rec.raw.kp >= 5) keep.push(v.keepRate);
    maxExp = Math.max(maxExp, experienceMatches(rec, scope, pi));
    maxCapt = Math.max(maxCapt, scope.players.capt ? scope.players.capt[pi] || 0 : 0);
  }
  return { batQ: meanSd(bat), bowlQ: meanSd(bowl), batL: meanSd(batL), bowlL: meanSd(bowlL),
           keep: meanSd(keep), maxExp, maxCapt, nBat: bat.length, nBowl: bowl.length };
}

export function experienceMatches(rec, scope, pi) {
  const pre = scope.players.pre ? scope.players.pre[pi] || 0 : 0;
  return rec.careerM + pre;
}

export function scores(rec, scope, ref, pi) {
  const v = rawValues(rec, scope, pi);
  const capt = scope.players.capt ? scope.players.capt[pi] || 0 : 0;
  const vc = scope.players.vc ? scope.players.vc[pi] || 0 : 0;
  const exp = experienceMatches(rec, scope, pi);
  return {
    batQ: scale(v.batQ, ref.batQ),
    bowlQ: scale(v.bowlQ, ref.bowlQ),
    batL: scale(v.batL, ref.batL),
    bowlL: scale(v.bowlL, ref.bowlL),
    keep: scale(v.keepRate, ref.keep),
    exp: 100 * Math.log1p(exp) / Math.log1p(ref.maxExp),
    lead: scope.players.capt ? 100 * Math.log1p(capt + 0.5 * vc) / Math.log1p(ref.maxCapt + 0.5) : null,
    raw: v,
    expMatches: exp,
    captMatches: capt,
  };
}

/** Quality and legacy component for a given slot type. */
export function slotComponents(type, sc) {
  const z = (x) => (x === null ? 0 : x);
  switch (type) {
    case 'opener': case 'batter': case 'finisher':
      return { q: sc.batQ, l: sc.batL };
    case 'keeper':
      return { q: sc.batQ === null ? null : 0.85 * sc.batQ + 0.15 * (sc.keep ?? 50),
               l: sc.batL };
    case 'allrounder':
      return { q: sc.batQ === null || sc.bowlQ === null ? null : 0.5 * sc.batQ + 0.5 * sc.bowlQ,
               l: 0.5 * z(sc.batL) + 0.5 * z(sc.bowlL) };
    default:
      return { q: sc.bowlQ, l: sc.bowlL };
  }
}

export function utility(type, sc, weights) {
  const { q, l } = slotComponents(type, sc);
  if (q === null) return null;
  const parts = {
    quality: weights.quality * q,
    legacy: weights.legacy * (l ?? 0),
    experience: weights.experience * sc.exp,
    leadership: sc.lead === null ? 0 : weights.leadership * sc.lead,
  };
  const total = weights.quality + weights.legacy + weights.experience +
    (sc.lead === null ? 0 : weights.leadership);
  if (total <= 0) return null;
  const u = (parts.quality + parts.legacy + parts.experience + parts.leadership) / total;
  return { u, parts: Object.fromEntries(Object.entries(parts).map(([k, x]) => [k, x / total])) };
}
