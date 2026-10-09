// Window, team and recency filtering over additive season rows.
// Scope data is columnar: scope.seasons[col][i]. Every column is a sum, so a
// weighted sum over the selected rows is an unbiased windowed total.

export const SUM_COLS = [
  'm', 'kp', 'bi', 'no', 'r', 'b', 'out', 'f4', 'f6', 'd0', 'h50', 'h100',
  'p12', 'p3', 'p46', 'p7', 'ba',
  'wi', 'wb', 'wr', 'ww', 'wm', 'wd', 'wx', 'wn', 'wc', 'wp0', 'wp1', 'wp2', 'w3', 'w5',
  'ct', 'kc', 'st', 'ro',
];

/**
 * @param {object} scope   scope JSON (players, seasons, teams)
 * @param {object} opts    {from, to, team (index|null), fullOnly, halfLife (years, 0 = none)}
 *   fullOnly keeps only matches between ICC Full Members (both sides).
 * @returns {Map<number, object>} player index -> {w: weighted sums, raw: unweighted sums,
 *   careerM (matches up to `to`), hs, teams: Map(team index -> matches), years}
 */
export function aggregate(scope, opts) {
  const s = scope.seasons;
  const n = s.p.length;
  const { from, to, team = null, fullOnly = false, halfLife = 0 } = opts;
  const out = new Map();
  const careerM = new Map();
  const fullTeam = scope.teamsFull || null;
  for (let i = 0; i < n; i++) {
    const y = s.y[i];
    const pi = s.p[i];
    if (fullOnly && (s.o[i] !== 1 || (fullTeam && !fullTeam[s.t[i]]))) continue;
    if (y <= to && (team === null || s.t[i] === team)) {
      careerM.set(pi, (careerM.get(pi) || 0) + s.m[i]);
    }
    if (y < from || y > to) continue;
    if (team !== null && s.t[i] !== team) continue;
    const wt = halfLife > 0 ? Math.pow(0.5, (to - y) / halfLife) : 1;
    let rec = out.get(pi);
    if (!rec) {
      rec = { w: {}, raw: {}, hs: 0, teams: new Map(), years: new Set() };
      for (const c of SUM_COLS) { rec.w[c] = 0; rec.raw[c] = 0; }
      out.set(pi, rec);
    }
    for (const c of SUM_COLS) {
      const v = s[c][i];
      if (v) { rec.w[c] += v * wt; rec.raw[c] += v; }
    }
    if (s.hs[i] > rec.hs) rec.hs = s.hs[i];
    rec.teams.set(s.t[i], (rec.teams.get(s.t[i]) || 0) + s.m[i]);
    rec.years.add(y);
  }
  for (const [pi, rec] of out) rec.careerM = careerM.get(pi) || rec.raw.m;
  return out;
}
