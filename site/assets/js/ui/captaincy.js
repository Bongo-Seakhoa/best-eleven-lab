// Captaincy records shared by the Captains page and player pages: the record
// key the Captains page uses in its ids parameter, links into that page, and a
// person's rows in the all-eras career lists.

export const MAX_COMPARE = 4;
// The Captains page's scope when its link names none.
export const SCOPE_DEFAULTS = { level: 'international', g: 'male', f: 'Test' };

/** Stable short key for a captaincy record, used in the ids query parameter. */
export function recordKey(r) {
  const str = [r.level, r.gender, r.format, r.country_or_team, r.competition, r.wikipedia_title || r.name].join('|');
  let x = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) { x ^= str.charCodeAt(i); x = Math.imul(x, 0x01000193); }
  return (x >>> 0).toString(36);
}

/**
 * The Captains page with this record ticked. A saved comparison of the same
 * scope keeps its captains and filters when there is room for one more;
 * otherwise the link starts a new comparison in the record's own scope.
 * Returns {href, others, already}: how many other captains the comparison
 * holds, and whether this record is in it already.
 */
export function compareHref(r, savedHref) {
  const key = recordKey(r);
  const franchise = r.level === 'franchise';
  const q = new URLSearchParams(String(savedHref || '').split('?')[1] || '');
  const ids = [...new Set((q.get('ids') || '').split(',').filter(Boolean))];
  const savedF = q.has('f') ? (q.get('f') === 'all' ? '' : q.get('f')) : SCOPE_DEFAULTS.f;
  const sameScope = !!savedHref && (q.get('level') || SCOPE_DEFAULTS.level) === r.level
    && (q.get('g') || SCOPE_DEFAULTS.g) === r.gender
    && (franchise ? !q.get('comp') || q.get('comp') === r.competition : !savedF || savedF === r.format);
  const already = ids.includes(key);
  if (sameScope && ids.length && (already || ids.length < MAX_COMPARE)) {
    if (!already) ids.push(key);
    q.set('ids', ids.join(','));
    return { href: `#/captains?${q}`, others: ids.length - 1, already };
  }
  const fresh = new URLSearchParams({ level: r.level, g: r.gender });
  if (franchise) { if (r.competition) fresh.set('comp', r.competition); } else fresh.set('f', r.format);
  fresh.set('ids', key);
  return { href: `#/captains?${fresh}`, others: 0, already: false };
}

/** Matching rows of an all-eras career list (column arrays), as objects. */
export function careerRows(H, ids, titles) {
  const P = H?.players;
  if (!P) return [];
  const cols = Object.keys(P), out = [];
  for (let i = 0; i < P.name.length; i++) {
    if ((P.id[i] && ids.has(P.id[i])) || (P.title[i] && titles.has(P.title[i]))) {
      const row = {};
      for (const c of cols) row[c] = P[c][i];
      out.push(row);
    }
  }
  return out;
}

/** Career figures that the lists actually give; zero counts are treated as not given. */
export function careerFigures(row) {
  const pos = (x) => (Number.isFinite(x) && x > 0 ? x : null);
  return {
    matches: pos(row.m), runs: pos(row.runs),
    avg: row.outs > 0 && row.runs >= 0 ? row.runs / row.outs : null,
    h100: row.h100 >= 0 ? row.h100 : null, h50: row.h50 >= 0 ? row.h50 : null,
    wkts: pos(row.wkts), bowlAvg: row.wkts > 0 && row.rc > 0 ? row.rc / row.wkts : null,
    ct: pos(row.ct), st: pos(row.st),
  };
}
