// Best XI settings: one definition of the state, its URL form, the engine
// settings it implies and its title. Shared by the Best XI and XI vs XI pages.
import * as data from './data.js';
import { PRESETS, defaultSlots, SLOT_TYPES, selectXI } from './engine/select.js';
import { selectHistoric } from './engine/historic.js';

export function defaults(partial = {}) {
  return {
    mode: 'bbb', tier: 'national', g: 'male', f: 'Test', lg: 'ipl', team: '', from: null, to: null,
    av: 'active', lens: 'balanced', ...PRESETS.balanced.weights, hl: PRESETS.balanced.halfLife,
    ev: 1, fo: 1, mpt: 4, mos: null, slots: '', comp: '', lock: '', excl: '', view: 'sheet', ...partial,
  };
}

const NUMERIC = ['from', 'to', 'quality', 'legacy', 'experience', 'leadership', 'hl', 'ev', 'fo', 'mpt', 'mos'];

/** State fields from URLSearchParams (or any iterable of [key, value]). */
export function fromQuery(q) {
  const st = {};
  for (const [k, v] of q) st[k] = v;
  for (const k of NUMERIC) if (st[k] != null && st[k] !== '') st[k] = Number(st[k]);
  return st;
}

export function toQuery(st) {
  const out = {};
  for (const [k, v] of Object.entries(st)) if (v !== null && v !== '' && v !== undefined) out[k] = v;
  return out;
}

export const queryString = (st) => new URLSearchParams(toQuery(st)).toString();

export const scopeKey = (st) => (st.tier === 'league' ? st.lg : `${st.g === 'male' ? 'men' : 'women'}-${st.f.toLowerCase()}`);
export const histKey = (st) => `${st.g === 'male' ? 'men' : 'women'}-${st.f.toLowerCase()}`;

/** Team shapes: the Best XI's balanced one, or free elevens for fantasy matchups. */
export const COMPOSITIONS = {
  '': { label: 'Best XI shape', note: 'Openers, batters, a keeper, all-rounders and bowlers, as the Best XI picks them' },
  free: { label: 'Free', note: 'The best eleven players of any kind' },
  bat: { label: 'All batters', note: 'Eleven batting picks' },
  bowl: { label: 'All bowlers', note: 'Eleven bowling picks' },
};
const FREE_SLOT = { free: 'any', bat: 'bat', bowl: 'bowl' };

/** Slots a state asks for: a free shape, or the Best XI shape (default or set by hand). */
export function slotsFor(st, family) {
  if (FREE_SLOT[st.comp]) return [{ type: FREE_SLOT[st.comp], count: 11 }];
  return parseSlots(st.slots, family);
}

export function parseSlots(str, family) {
  if (!str) return defaultSlots(family);
  const slots = str.split(',').map((x) => { const m = x.match(/^([a-z]+)(\d+)$/); return m && { type: m[1], count: +m[2] }; })
    .filter((x) => x && SLOT_TYPES[x.type]);
  return slots.length ? slots : defaultSlots(family);
}
export const slotsStr = (slots) => slots.filter((s) => s.count > 0).map((s) => `${s.type}${s.count}`).join(',');

/** Teams a user can pick: composite exhibition sides (ICC World XI, Asia XI, ...) are not teams to select for. */
export function selectableTeams(teams, tier) {
  const list = teams.filter((t) => !data.COMPOSITE_SIDES.has(t));
  return tier === 'national'
    ? list.sort((a, b) => (data.FULL_MEMBERS.includes(b) - data.FULL_MEMBERS.includes(a)) || a.localeCompare(b))
    : list.sort();
}

/**
 * Load the data a state needs and clamp the state to what that data offers
 * (window, team, availability, overseas cap). Mutates `st`; returns {scope, hist}.
 */
export async function resolve(st, meta) {
  if (st.mode === 'hist') {
    if (!['Test', 'ODI'].includes(st.f) || st.tier === 'league') { st.f = ['Test', 'ODI'].includes(st.f) ? st.f : 'Test'; st.tier = 'national'; }
    const hist = await data.historic(histKey(st));
    if (st.team && (!hist.countries.includes(st.team) || data.COMPOSITE_SIDES.has(st.team))) st.team = '';
    return { scope: null, hist };
  }
  if (!meta.scopes.some((s) => s.key === scopeKey(st))) { st.tier = 'national'; st.f = 'Test'; }
  const scope = await data.scope(scopeKey(st));
  const [y0, y1] = scope.years;
  if (st.to == null || st.to > y1 || st.to < y0) st.to = y1;
  if (st.from == null || st.from < y0 || st.from > st.to) {
    st.from = st.tier === 'league' ? y0 : Math.max(y0, st.to - 3);
    // A whole-history window opens on the all-time lens unless the user chose one.
    if (st.from === y0 && st.lens === 'balanced') Object.assign(st, PRESETS.alltime.weights, { hl: 0, lens: 'alltime', av: 'any' });
  }
  if (st.team && (!scope.teams.includes(st.team) || data.COMPOSITE_SIDES.has(st.team))) st.team = '';
  if (st.tier === 'league' && st.mos == null) st.mos = scope.maxOverseas ?? null;
  if (!scope.availability.squads && st.av === 'squad') st.av = 'active';
  return { scope, hist: null };
}

/** Engine settings for a ball-by-ball state. */
export function engineSettings(st, scope) {
  const slots = slotsFor(st, scope ? scope.family : 'multi');
  const idx = st.team && scope ? scope.teams.indexOf(st.team) : -1;
  const team = idx === -1 ? null : idx;
  return {
    from: st.from, to: st.to, team,
    fullOnly: scope?.tier === 'national' && !!st.fo && team === null,
    halfLife: st.hl, evidence: st.ev, availability: st.av,
    weights: { quality: st.quality, legacy: st.legacy, experience: st.experience, leadership: st.leadership },
    slots, maxPerTeam: scope?.tier === 'national' && team === null ? (st.mpt || null) : null,
    maxOverseas: scope?.tier === 'league' && team === null ? (st.mos ?? null) : null,
    locks: new Set(st.lock ? st.lock.split(',') : []), excludes: new Set(st.excl ? st.excl.split(',') : []),
    flexible: !st.slots && !FREE_SLOT[st.comp],   // only the default shape bends; a shape set by hand is kept or reported infeasible
  };
}

/** "2 openers, 3 all-rounders, …" for a composition. */
export function compositionText(slots) {
  return slots.filter((s) => s.count > 0)
    .map((s) => `${s.count} ${SLOT_TYPES[s.type].label.toLowerCase()}${s.count > 1 ? 's' : ''}`).join(', ');
}

/** Run the selection a state describes (either evidence base). */
export function selectFor(st, { scope, hist }) {
  if (st.mode === 'hist') {
    return selectHistoric(hist, {
      country: st.team || null, fullOnly: !!st.fo,
      weights: { quality: st.quality, legacy: st.legacy, experience: st.experience, leadership: st.leadership },
      maxPerTeam: st.team ? null : (st.mpt || null),
      slots: FREE_SLOT[st.comp] ? [{ type: FREE_SLOT[st.comp], count: 11 }] : undefined,
      locks: new Set(st.lock ? st.lock.split(',') : []), excludes: new Set(st.excl ? st.excl.split(',') : []),
    });
  }
  return selectXI(scope, engineSettings(st, scope));
}

/** "South Africa ODI XI", "IPL all-franchise XI", "World all-time Test XI". */
export function xiTitle(st, { scope }) {
  if (st.mode === 'hist') return `${st.team || 'World'} all-time ${st.f} XI`;
  if (scope.tier === 'league') return `${st.team || scope.short + ' all-franchise'} XI`;
  return `${st.team || 'World'} ${scope.format} XI`;
}

/** "2023–2026" or "2025". */
export const windowText = (st) => (st.from === st.to ? String(st.from) : `${st.from}–${st.to}`);
